#!/bin/bash
C=vjbih0pvgs6inosh9ramfqlm-144035652234
docker exec "$C" find /app -name '*.ts' -o -name '*.tsx' 2>/dev/null | head -5
docker exec "$C" grep -r "profile_pic" /app --include='*.ts' --include='*.tsx' -l 2>/dev/null | head -15
docker exec "$C" grep -r "profile_pic" /app --include='*.ts' --include='*.tsx' -m 2 2>/dev/null | head -30
