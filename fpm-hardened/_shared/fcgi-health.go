// Minimal FastCGI health probe for php-fpm status endpoint.
// Compiled to a static binary; no PHP CLI or interpreter required at runtime.
//
// Env vars (all optional):
//   FCGI_CONNECT     — address to dial, default 127.0.0.1:9000
//   FCGI_STATUS_PATH — FastCGI SCRIPT_NAME to request, default /status
//   FCGI_TIMEOUT     — dial+read timeout in seconds, default 2
package main

import (
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"os"
	"strconv"
	"strings"
	"time"
)

const (
	fcgiVersion      = 1
	fcgiBeginRequest = 1
	fcgiEndRequest   = 3
	fcgiParams       = 4
	fcgiStdin        = 5
	fcgiStdout       = 6
	fcgiResponder    = 1
)

func main() {
	addr := env("FCGI_CONNECT", "127.0.0.1:9000")
	statusPath := env("FCGI_STATUS_PATH", "/status")
	timeoutSecs, parseErr := strconv.Atoi(env("FCGI_TIMEOUT", "2"))
	if parseErr != nil || timeoutSecs <= 0 {
		timeoutSecs = 2
	}
	timeout := time.Duration(timeoutSecs) * time.Second
	network, dialAddr := fcgiEndpoint(addr)

	conn, err := net.DialTimeout(network, dialAddr, timeout)
	if err != nil {
		fmt.Fprintf(os.Stderr, "fcgi-health: connect %s %s: %v\n", network, dialAddr, err)
		os.Exit(1)
	}
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(timeout)) //nolint:errcheck

	const reqID = uint16(1)

	// FCGI_BEGIN_REQUEST body: role (2 bytes) + flags (1 byte) + reserved (5 bytes) = 8 bytes
	beginBody := make([]byte, 8)
	binary.BigEndian.PutUint16(beginBody[0:2], fcgiResponder)
	if err := writeRecord(conn, fcgiBeginRequest, reqID, beginBody); err != nil {
		fmt.Fprintf(os.Stderr, "fcgi-health: begin request: %v\n", err)
		os.Exit(1)
	}

	// FCGI_PARAMS
	params := [][2]string{
		{"REQUEST_METHOD", "GET"},
		{"SCRIPT_NAME", statusPath},
		{"SCRIPT_FILENAME", statusPath},
		{"REQUEST_URI", statusPath},
		{"SERVER_PROTOCOL", "HTTP/1.1"},
		{"GATEWAY_INTERFACE", "CGI/1.1"},
		{"CONTENT_LENGTH", "0"},
	}
	var paramBuf []byte
	for _, kv := range params {
		paramBuf = append(paramBuf, encodeNameValue(kv[0], kv[1])...)
	}
	if err := writeRecord(conn, fcgiParams, reqID, paramBuf); err != nil {
		fmt.Fprintf(os.Stderr, "fcgi-health: params: %v\n", err)
		os.Exit(1)
	}
	if err := writeRecord(conn, fcgiParams, reqID, nil); err != nil { // empty params = end of params stream
		fmt.Fprintf(os.Stderr, "fcgi-health: params terminator: %v\n", err)
		os.Exit(1)
	}
	if err := writeRecord(conn, fcgiStdin, reqID, nil); err != nil { // empty stdin = end of stdin stream
		fmt.Fprintf(os.Stderr, "fcgi-health: stdin terminator: %v\n", err)
		os.Exit(1)
	}

	// Read response records until FCGI_END_REQUEST
	var stdout strings.Builder
	hdr := make([]byte, 8)
	gotEnd := false
	for {
		if _, err := io.ReadFull(conn, hdr); err != nil {
			break
		}
		recType := hdr[1]
		contentLen := binary.BigEndian.Uint16(hdr[4:6])
		paddingLen := hdr[6]

		body := make([]byte, int(contentLen))
		if contentLen > 0 {
			if _, err := io.ReadFull(conn, body); err != nil {
				break
			}
		}
		if paddingLen > 0 {
			pad := make([]byte, int(paddingLen))
			if _, err := io.ReadFull(conn, pad); err != nil {
				break
			}
		}

		if recType == fcgiStdout {
			stdout.Write(body)
		}
		if recType == fcgiEndRequest {
			gotEnd = true
			break
		}
	}

	if !gotEnd {
		fmt.Fprintln(os.Stderr, "fcgi-health: incomplete response (no FCGI_END_REQUEST)")
		os.Exit(1)
	}

	// Parse FastCGI/HTTP-style response: headers before \r\n\r\n, body after.
	resp := stdout.String()
	parts := strings.SplitN(resp, "\r\n\r\n", 2)
	headers := ""
	body := resp
	if len(parts) == 2 {
		headers = parts[0]
		body = parts[1]
	}

	// Fail on non-200 HTTP status header (e.g. "Status: 404 Not Found").
	for _, line := range strings.Split(headers, "\r\n") {
		if strings.HasPrefix(strings.ToLower(line), "status:") {
			fields := strings.Fields(strings.TrimSpace(line[len("status:"):]))
			if len(fields) == 0 || fields[0] != "200" {
				fmt.Fprintf(os.Stderr, "fcgi-health: fpm status non-200: %s\n", strings.TrimSpace(line))
				os.Exit(1)
			}
			break
		}
	}

	out := strings.TrimSpace(body)
	if out == "" || strings.Contains(out, "File not found") {
		fmt.Fprintln(os.Stderr, "fcgi-health: fpm status unavailable")
		os.Exit(1)
	}
}

func writeRecord(w io.Writer, recType uint8, reqID uint16, body []byte) error {
	length := len(body)
	padding := (8 - (length % 8)) % 8
	hdr := [8]byte{
		fcgiVersion,
		recType,
		byte(reqID >> 8), byte(reqID),
		byte(length >> 8), byte(length),
		byte(padding),
		0,
	}
	if err := writeFull(w, hdr[:]); err != nil {
		return err
	}
	if err := writeFull(w, body); err != nil {
		return err
	}
	if padding > 0 {
		if err := writeFull(w, make([]byte, padding)); err != nil {
			return err
		}
	}
	return nil
}

func writeFull(w io.Writer, buf []byte) error {
	for len(buf) > 0 {
		n, err := w.Write(buf)
		if err != nil {
			return err
		}
		if n == 0 {
			return io.ErrShortWrite
		}
		buf = buf[n:]
	}
	return nil
}

func encodeNameValue(name, value string) []byte {
	buf := make([]byte, 0, len(name)+len(value)+8)
	buf = append(buf, fcgiLen(len(name))...)
	buf = append(buf, fcgiLen(len(value))...)
	buf = append(buf, name...)
	buf = append(buf, value...)
	return buf
}

func fcgiLen(n int) []byte {
	if n < 128 {
		return []byte{byte(n)}
	}
	b := make([]byte, 4)
	binary.BigEndian.PutUint32(b, uint32(n)|0x80000000)
	return b
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func fcgiEndpoint(addr string) (network, dialAddr string) {
	switch {
	case strings.HasPrefix(addr, "unix://"):
		return "unix", strings.TrimPrefix(addr, "unix://")
	case strings.HasPrefix(addr, "unix:"):
		return "unix", strings.TrimPrefix(addr, "unix:")
	case strings.HasPrefix(addr, "/"):
		return "unix", addr
	default:
		return "tcp", addr
	}
}
