#!/bin/bash

BASE_URL="http://localhost:8001"

EMAIL="ishwar@gmail.com"
PASSWORD="Ishwar@1234"
FULL_NAME="Ishwar"

echo "==============================="
echo "1️⃣ Signing up user..."
echo "==============================="

curl -s -X POST "$BASE_URL/auth/signup" \
-H "Content-Type: application/json" \
-d "{
  \"email\": \"$EMAIL\",
  \"password\": \"$PASSWORD\",
  \"full_name\": \"$FULL_NAME\"
}" | jq

echo ""
echo "==============================="
echo "2️⃣ Logging in..."
echo "==============================="

LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/auth/login" \
-H "Content-Type: application/json" \
-d "{
  \"email\": \"$EMAIL\",
  \"password\": \"$PASSWORD\"
}")

echo $LOGIN_RESPONSE | jq

TOKEN=$(echo $LOGIN_RESPONSE | jq -r '.access_token')
USER_ID=$(echo $LOGIN_RESPONSE | jq -r '.user_id')

echo ""
echo "Extracted TOKEN:"
echo $TOKEN
echo ""
echo "Extracted USER_ID:"
echo $USER_ID
echo ""

echo "==============================="
echo "3️⃣ Ingesting Memory Messages..."
echo "==============================="

MESSAGES=(
"I invested 50000 in HDFC mutual fund in January 2024."
"I bought 20 shares of TCS at 3500 each."
"I invested 100000 in PPF for long term savings."
"My retirement goal is 2 crore by 2055."
"I want to buy a house worth 80 lakh by 2030."
"I have a moderate risk appetite."
"I prefer mutual funds over individual stocks."
"I added another 20000 to HDFC mutual fund in March 2024."
"Actually I invested 60000 in HDFC mutual fund."
"I plan to review my portfolio every December."
)

for MESSAGE in "${MESSAGES[@]}"
do
  echo ""
  echo "➡️  Ingesting: $MESSAGE"

  curl -s -X POST "$BASE_URL/chat" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"user_id\": \"$USER_ID\",
    \"message\": \"$MESSAGE\"
  }" | jq
done

echo ""
echo "==============================="
echo "✅ All memories ingested successfully!"
echo "==============================="