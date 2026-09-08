#!/usr/bin/env bash
# 端到端冒烟测试：登录 -> 建题库 -> 建题 -> 答题 -> 历史 -> 错题本
set -euo pipefail
BASE="http://127.0.0.1:5003"
SLUG="cipt"

say() { printf '\n=== %s ===\n' "$*"; }

say "登录 nianyu"
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"nianyu","password":"Admin12345"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
echo "token 前缀: ${TOKEN:0:20}..."
AUTH=(-H "Authorization: Bearer $TOKEN" -H "X-Exam-Slug: $SLUG" -H 'Content-Type: application/json')

say "创建题库"
BANK_ID=$(curl -s -X POST "$BASE/api/banks" "${AUTH[@]}" \
  -d '{"name":"冒烟测试题库","description":"E2E smoke"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "bank_id=$BANK_ID"

say "创建 3 道题（单选/多选/判断）"
Q1=$(curl -s -X POST "$BASE/api/questions" "${AUTH[@]}" -d "{\"bank_id\":$BANK_ID,\"question_type\":\"single\",\"content\":\"What does PII stand for?\",\"options\":[{\"key\":\"A\",\"text\":\"Personally Identifiable Information\"},{\"key\":\"B\",\"text\":\"Private Internet Index\"}],\"correct_answer\":\"A\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
Q2=$(curl -s -X POST "$BASE/api/questions" "${AUTH[@]}" -d "{\"bank_id\":$BANK_ID,\"question_type\":\"multiple\",\"content\":\"Which are privacy principles?\",\"options\":[{\"key\":\"A\",\"text\":\"Data minimization\"},{\"key\":\"B\",\"text\":\"Purpose limitation\"},{\"key\":\"C\",\"text\":\"Unlimited retention\"}],\"correct_answer\":\"AB\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
Q3=$(curl -s -X POST "$BASE/api/questions" "${AUTH[@]}" -d "{\"bank_id\":$BANK_ID,\"question_type\":\"truefalse\",\"content\":\"GDPR applies only in the US.\",\"options\":[{\"key\":\"T\",\"text\":\"True\"},{\"key\":\"F\",\"text\":\"False\"}],\"correct_answer\":\"F\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
echo "questions: $Q1 $Q2 $Q3"

say "开始顺序答题会话"
START=$(curl -s -X POST "$BASE/api/quiz/start" "${AUTH[@]}" -d "{\"bank_id\":$BANK_ID,\"mode\":\"sequential\"}")
SESSION_ID=$(echo "$START" | python3 -c 'import sys,json;print(json.load(sys.stdin)["session"]["id"])')
echo "session_id=$SESSION_ID"

say "作答：Q1 正确(A)，Q2 错误(A)，Q3 正确(F)"
curl -s -X POST "$BASE/api/quiz/answer" "${AUTH[@]}" -d "{\"session_id\":$SESSION_ID,\"question_id\":$Q1,\"user_answer\":\"A\"}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("Q1 is_correct=",d.get("is_correct"))'
curl -s -X POST "$BASE/api/quiz/answer" "${AUTH[@]}" -d "{\"session_id\":$SESSION_ID,\"question_id\":$Q2,\"user_answer\":\"A\"}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("Q2 is_correct=",d.get("is_correct"))'
curl -s -X POST "$BASE/api/quiz/answer" "${AUTH[@]}" -d "{\"session_id\":$SESSION_ID,\"question_id\":$Q3,\"user_answer\":\"F\"}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("Q3 is_correct=",d.get("is_correct"))'

say "结束会话"
curl -s -X POST "$BASE/api/quiz/finish" "${AUTH[@]}" -d "{\"session_id\":$SESSION_ID}" | python3 -m json.tool

say "答题历史"
curl -s "$BASE/api/quiz/history" "${AUTH[@]}" | python3 -m json.tool

say "错题本（应包含 Q2）"
curl -s "$BASE/api/wrong" "${AUTH[@]}" | python3 -m json.tool

say "冒烟测试完成"
