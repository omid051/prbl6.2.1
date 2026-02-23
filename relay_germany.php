<?php
// این فایل را در هاست آلمان قرار بده
header('Content-Type: application/json');

// آدرس دقیق فایل رله ایران را در خط زیر قرار بده:
$iran_relay_url = 'https://iranvisametric.com/bls/relay_iran.php';

$raw_input = file_get_contents('php://input');
$headers = getallheaders();
$auth_key = isset($headers['Authorization']) ? $headers['Authorization'] : '';

$ch = curl_init($iran_relay_url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $raw_input);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    'Content-Type: application/json',
    'Authorization: ' . $auth_key
]);

$response = curl_exec($ch);
$httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

http_response_code($httpcode);
echo $response;
?>