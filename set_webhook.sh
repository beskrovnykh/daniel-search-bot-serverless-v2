#!/bin/bash

# The URL for your function (passed as an argument)
FUNCTION_URL=$1

# The API endpoint for setting the webhook
API_URL="https://api.telegram.org/bot$TELEGRAM_TOKEN/setWebhook"

# The JSON payload for the API request
JSON_DATA=$(printf '{"url": "%s"}' $FUNCTION_URL)

# The curl command to set the webhook
curl --request POST --url $API_URL --header 'content-type: application/json' --data "$JSON_DATA"
