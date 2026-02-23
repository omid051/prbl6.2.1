<?php
// webhook.php

// تنظیمات فایل‌ها
$json_file = 'visa_codes.json';      // فایل اصلی ذخیره کدها
$others_file = 'other_emails.html';  // فایل لاگ ایمیل‌های ناشناس

// ---------------------------------------------------------
// 1. دریافت داده‌ها
// ---------------------------------------------------------
$raw_input = file_get_contents('php://input');
$data = json_decode($raw_input, true);

if (!$data && !empty($_POST)) {
    $data = $_POST;
}

if (!$data) {
    http_response_code(200);
    exit('No data received');
}

$plain_body = isset($data['plain']) ? $data['plain'] : '';
$html_body = isset($data['html']) ? $data['html'] : '';

$clean_html = str_ireplace(['<br>', '<br/>', '<br />', '</p>', '</div>'], " \n", $html_body);
$clean_html = strip_tags($clean_html);
$search_text = $plain_body . "\n " . $clean_html;

$email_pattern = '/Dear[\s:\-]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/i';
preg_match($email_pattern, $search_text, $email_matches);

$code_pattern = '/\b(\d{6})\b/';
preg_match($code_pattern, $search_text, $code_matches);

// ---------------------------------------------------------
// 3. ذخیره‌سازی با سیستم File Locking
// ---------------------------------------------------------

if (!empty($email_matches[1]) && !empty($code_matches[1])) {
    $raw_email = $email_matches[1];
    $raw_email = str_ireplace('Greetings', '', $raw_email);
    $target_email = strtolower(trim($raw_email));
    
    $verification_code = $code_matches[1];

    // ایجاد سیستم قفل برای جلوگیری از تداخل (Race Condition) هنگام دریافت 5 ایمیل همزمان
    $fp = fopen($json_file, 'c+');
    
    if (flock($fp, LOCK_EX)) { // گرفتن قفل انحصاری فایل
        $json_content = '';
        while (!feof($fp)) {
            $json_content .= fread($fp, 8192);
        }
        
        $current_data = json_decode($json_content, true) ?: [];

        $now = time();
        foreach ($current_data as $email => $info) {
            if (isset($info['received_at'])) {
                $received_time = strtotime($info['received_at']);
                if (($now - $received_time) > 600) {
                    unset($current_data[$email]);
                }
            }
        }

        $current_data[$target_email] = [
            'code' => $verification_code,
            'received_at' => date('Y-m-d H:i:s')
        ];

        ftruncate($fp, 0); // پاک کردن محتوای قبلی فایل
        rewind($fp); // بازگشت به ابتدای فایل
        fwrite($fp, json_encode($current_data, JSON_PRETTY_PRINT));
        fflush($fp);
        flock($fp, LOCK_UN); // آزادسازی قفل
    }
    fclose($fp);

} else {
    // >> ایمیل ناشناس <<
    if (file_exists($others_file) && filesize($others_file) > 2 * 1024 * 1024) { 
        unlink($others_file);
    }

    $headers = isset($data['headers']) ? $data['headers'] : [];
    $subject = isset($headers['Subject']) ? $headers['Subject'] : 'No Subject';
    $from = isset($headers['From']) ? $headers['From'] : 'Unknown';

    $log_entry = "<div style='background:#f4f4f4; border:1px solid #ddd; margin:10px 0; padding:15px; font-family:sans-serif;'>";
    $log_entry .= "<p><strong>From:</strong> $from <br> <strong>Subject:</strong> $subject <br> <strong>Date:</strong> " . date('Y-m-d H:i:s') . "</p>";
    $log_entry .= "<div style='max-height:300px; overflow-y:auto; border-top:1px solid #ccc; padding-top:10px;'>" . ($html_body ?: nl2br($plain_body)) . "</div>";
    $log_entry .= "</div>";

    file_put_contents($others_file, $log_entry, FILE_APPEND);
}

http_response_code(200);
echo "Processed";
?>