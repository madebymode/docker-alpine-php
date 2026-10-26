<?php

// Run only in the disposable FPM smoke-test container.
header('Content-Type: application/json');

$expected = [
    'memory_limit' => '512M',
    'opcache.enable' => '1',
    'opcache.enable_cli' => '1',
    'opcache.memory_consumption' => '256',
    'opcache.interned_strings_buffer' => '32',
    'opcache.max_accelerated_files' => '32531',
    'opcache.force_restart_timeout' => '180',
    'opcache.save_comments' => '1',
    'opcache.enable_file_override' => '0',
    'opcache.validate_timestamps' => '0',
    'opcache.jit' => 'disable',
    'opcache.jit_buffer_size' => '0',
    'opcache.preload' => '',
    'opcache.preload_user' => '',
    'realpath_cache_size' => '4096K',
    'realpath_cache_ttl' => '600',
];

$errors = [];
if (PHP_SAPI !== 'fpm-fcgi') {
    $errors[] = 'Expected PHP-FPM, got ' . PHP_SAPI;
}
foreach ($expected as $name => $value) {
    if (ini_get($name) !== $value) {
        $errors[] = sprintf('%s: expected %s, got %s', $name, var_export($value, true), var_export(ini_get($name), true));
    }
}
if (filter_var(ini_get('expose_php'), FILTER_VALIDATE_BOOLEAN)) {
    $errors[] = 'expose_php must be disabled';
}

// Craft 5 requires these PHP extensions; this image provides the MySQL driver.
foreach (['bcmath', 'ctype', 'curl', 'gd', 'iconv', 'intl', 'json', 'mbstring', 'openssl', 'pcre', 'pdo_mysql', 'PDO', 'Reflection', 'SPL', 'zip', 'dom'] as $extension) {
    if (!extension_loaded($extension)) {
        $errors[] = 'Missing Craft-required PHP extension: ' . $extension;
    }
}

$status = function_exists('opcache_get_status') ? opcache_get_status(false) : false;
if (!is_array($status) || empty($status['opcache_enabled'])) {
    $errors[] = 'OPcache is not active in PHP-FPM';
}
if (!isset($status['jit']) || $status['jit']['enabled'] || $status['jit']['on'] || $status['jit']['buffer_size'] !== 0) {
    $errors[] = 'JIT must be disabled with no code buffer';
}

if ($errors) {
    http_response_code(500);
    error_log('DHI performance smoke test failed: ' . implode('; ', $errors));
}
echo json_encode(['ok' => !$errors, 'errors' => $errors], JSON_THROW_ON_ERROR);
