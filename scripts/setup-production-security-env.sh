#!/bin/bash
# Продакшен-настройки безопасности для Coolify app 14 (clicks).
set -euo pipefail

echo "=== Set APP_ENV and SESSION_COOKIE_HTTPS_ONLY (app 14) ==="
docker exec coolify php artisan tinker --execute="
use App\Models\Application;
use Illuminate\Support\Str;

\$app = Application::find(14);
if (!\$app) { echo 'app missing'; exit(1); }

\$vars = [
  'APP_ENV' => 'production',
  'SESSION_COOKIE_HTTPS_ONLY' => 'true',
];

foreach (\$vars as \$key => \$value) {
  \$row = \$app->environment_variables()->where('key', \$key)->where('is_preview', false)->first();
  if (\$row) {
    \$row->value = \$value;
    \$row->save();
    echo \"updated \$key\\n\";
  } else {
    \$app->environment_variables()->create([
      'key' => \$key,
      'value' => \$value,
      'is_preview' => false,
      'is_literal' => false,
      'is_shown_once' => false,
      'is_multiline' => false,
      'is_required' => false,
      'uuid' => (string) Str::uuid(),
      'version' => '4.0.0',
    ]);
    echo \"created \$key\\n\";
  }
}

\$weak = [];
foreach (['SECRET_KEY', 'ADMIN_PASSWORD', 'API_TOKEN'] as \$k) {
  \$row = \$app->environment_variables()->where('key', \$k)->where('is_preview', false)->first();
  if (!\$row || trim((string)\$row->value) === '') {
    \$weak[] = \$k . ' (missing)';
  }
}
if (\$weak) {
  echo 'WARN: check secrets: ' . implode(', ', \$weak) . \"\\n\";
} else {
  echo \"SECRET_KEY, ADMIN_PASSWORD and API_TOKEN are set\\n\";
}
"

echo "=== Redeploy clicks ==="
bash /tmp/coolify-redeploy-clicks.sh HEAD
