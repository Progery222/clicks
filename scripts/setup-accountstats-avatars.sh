#!/bin/bash
# Добавить ACCOUNTSTATS_DATABASE_URL в Coolify (app 14) и пересобрать.
set -euo pipefail

DB_URL="${ACCOUNTSTATS_DATABASE_URL:-postgresql://socialhub:b344548afd818cc1332669cba0ef2ffd@t14ip5v8bhxqxpt2n6ujilme:5432/social_dashboard}"

echo "=== Ensure ACCOUNTSTATS_DATABASE_URL in Coolify app 14 ==="
docker exec coolify php artisan tinker --execute="
use App\Models\Application;
use Illuminate\Support\Str;
\$app = Application::find(14);
if (!\$app) { echo 'app missing'; exit(1); }
\$row = \$app->environment_variables()->where('key', 'ACCOUNTSTATS_DATABASE_URL')->where('is_preview', false)->first();
if (\$row) {
  \$row->value = '${DB_URL}';
  \$row->save();
  echo 'updated env\n';
} else {
  \$app->environment_variables()->create([
    'key' => 'ACCOUNTSTATS_DATABASE_URL',
    'value' => '${DB_URL}',
    'is_preview' => false,
    'is_literal' => false,
    'is_shown_once' => false,
    'is_multiline' => false,
    'is_required' => false,
    'uuid' => (string) Str::uuid(),
    'version' => '4.0.0',
  ]);
  echo 'created env\n';
}
"

echo "=== Clear favicon placeholders in links DB ==="
CLICKS_PG=ns4nylsxbxjslgqgx73jog4s
docker exec "$CLICKS_PG" psql -U postgres -d postgres -c \
  "UPDATE links SET account_avatar_url = NULL WHERE account_avatar_url ILIKE '%google.com/s2/favicons%';"

echo "=== Redeploy clicks ==="
bash /tmp/coolify-redeploy-clicks.sh HEAD
