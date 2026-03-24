#!/bin/bash
# Health check for Skylight Photos API
# Installed as cron: */5 * * * * /opt/skylight-photos/deploy/healthcheck.sh

SERVICE="skylight-photos-api"
HEALTH_URL="http://127.0.0.1:8007/health"
LOG_TAG="skylight-healthcheck"

if ! curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
    logger -t "$LOG_TAG" "Health check failed — restarting $SERVICE"
    systemctl restart "$SERVICE"
    sleep 3
    if curl -sf --max-time 5 "$HEALTH_URL" > /dev/null 2>&1; then
        logger -t "$LOG_TAG" "Service recovered after restart"
    else
        logger -t "$LOG_TAG" "Service still unhealthy after restart"
    fi
fi
