#!/bin/bash
# Trusted, one-time activation after the first healthy release.
set -euo pipefail
test "$(id -u)" = 0
exec 9>/run/lock/sanaebi-operation.lock
flock 9
candidate=/etc/sanaebi/nginx-vhost.pending
active=/etc/nginx/sites-available/sanaebi
backup=/etc/sanaebi/nginx-vhost.before-production
test -f /srv/sanaebi/current/web/index.html
curl --fail --silent --show-error http://127.0.0.1:18000/health/ready > /dev/null
changed=false
if ! cmp --silent "$candidate" "$active"; then
    if test -e "$backup"; then
        echo 'Vhost differs after activation; inspect changes before replacing it.' >&2
        exit 1
    fi
    cp --preserve=mode,ownership "$active" "$backup"
    chmod 600 "$backup"
    install -m 644 "$candidate" "$active"
    changed=true
fi
# Re-run even when files match: an earlier process may have died before reload.
if ! nginx -t || ! systemctl reload nginx; then
    if "$changed"; then
        install -m 644 "$backup" "$active"
        if nginx -t && systemctl reload nginx; then
            rm -f "$backup"
        else
            echo 'Nginx restore failed; original backup retained.' >&2
        fi
    fi
    exit 1
fi
systemctl enable --now sanaebi-production-reset.timer sanaebi-production-backup.timer
echo 'Production HTTPS and maintenance timers are active.'
