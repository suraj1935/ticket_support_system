# Question Evaluation Results

Dataset: `support_tickets.csv` (2000 tickets, created_at 2025-10-01 to 2026-09-30).
Gold answers are computed with pandas directly from the CSV. Scoring is exact match on the answer (counts as integers, averages at the 2 decimals the system prints, group-by as the full {group: value} set, top-N as entity + value; a right entity with the wrong direction word, e.g. "lowest" for a highest-average question, fails).
Reproduce: `python eval/run_eval.py`.

## Overall

| Category | n | regex | Ollama Cloud gpt-oss:120b-cloud |
|---|---|---|---|
| count | 6 | 2/6 | 6/6 |
| average | 5 | 1/5 | 5/5 |
| group-by | 6 | 4/6 | 6/6 |
| filter | 4 | 0/4 | 4/4 |
| date range | 3 | 0/3 | 3/3 |
| top agent | 3 | 3/3 | 3/3 |
| top category | 3 | 2/3 | 3/3 |
| **All in-scope** | 30 | **12/30 (40.0%)** | **30/30 (100.0%)** |

### Correct vs refused vs confidently wrong (in-scope, n=30)

Refused = no data and an error message (including the system failing to build a valid plan). Confidently wrong = a normal-looking answer that does not match the gold answer.

| Mode | Correct | Refused | Confidently wrong |
|---|---|---|---|
| regex | 12 | 18 | 0 |
| Ollama Cloud gpt-oss:120b-cloud | 30 | 0 | 0 |

- Ollama Cloud gpt-oss:120b-cloud: 35 LLM calls, 0 returned nothing (these fall back to the regex parser, so a wrong answer in this mode may come from the fallback).

## Out-of-scope questions (5)

A refusal is the safe outcome (no data, error message). Anything else is an answer the system was never designed to give, so it is recorded as a wrong answer.

| Type | Question | regex | Ollama Cloud gpt-oss:120b-cloud |
|---|---|---|---|
| comparison | Compare the average resolution time of Billing tickets versus Technical tickets. | Refused | WRONG ANSWER: 2 groups found. [2 rows: [{'category': 'Billing', 'avg_resolution_time_hrs': 11.401785714285714}, {'category': 'Technical', 'avg_resolution_time_hrs': 11.145785876993166}]...] |
| comparison | Are critical tickets resolved faster than low priority tickets? | Refused | WRONG ANSWER: 2 groups found. [2 rows: [{'priority': 'Critical', 'avg_resolution_time_hrs': 5.90373831775701}, {'priority': 'Low', 'avg_resolution_time_hrs': 14.200902527075813}]...] |
| trend | What is the trend in ticket volume by month? | Refused | Refused |
| median | What is the median resolution time? | Refused | Refused |
| percentile | What is the 90th percentile of response time? | Refused | Refused |
| **Refused** | | **5/5** | **3/5** |

## Per-question results: regex

| # | Category | Question | Result | Gold | System answer |
|---|---|---|---|---|---|
| 1 | count | How many tickets are there in total? | REFUSED | want 2000 | I had trouble answering that: I couldn't understand that question. |
| 2 | count | How many tickets are unresolved? | PASS | want 47 | 47 tickets match this query. |
| 3 | count | How many tickets are open? | REFUSED | want 30 | I had trouble answering that: I couldn't understand that question. |
| 4 | count | How many critical tickets are unresolved? | PASS | want 19 | 19 tickets match this query. |
| 5 | count | How many tickets are escalated? | REFUSED | want 17 | I had trouble answering that: I couldn't understand that question. |
| 6 | count | How many resolved tickets are in the Billing category? | REFUSED | want 616 | I had trouble answering that: The fallback parser cannot map 'billing' in this question to a supported query. Rephrase it, or start Ollama for broader coverage. |
| 7 | average | What is the average customer rating? | REFUSED | want 4.11 | I had trouble answering that: I couldn't understand that question. |
| 8 | average | What is the average resolution time in hours? | REFUSED | want 11.08 | I had trouble answering that: I couldn't understand that question. |
| 9 | average | What is the average response time in hours? | REFUSED | want 2.31 | I had trouble answering that: I couldn't understand that question. |
| 10 | average | What is the average rating for Technical tickets? | PASS | want 4.10 | The average customer rating is 4.10. |
| 11 | average | What is the average resolution time for critical tickets? | REFUSED | want 5.90 | I had trouble answering that: I couldn't understand that question. |
| 12 | group-by | How many tickets per priority? | PASS | want 4 groups | 4 groups found. [4 rows] |
| 13 | group-by | How many tickets per category? | PASS | want 3 groups | 3 groups found. [3 rows] |
| 14 | group-by | How many tickets per status? | PASS | want 3 groups | 3 groups found. [3 rows] |
| 15 | group-by | What is the average customer rating per category? | REFUSED | want 3 groups | I had trouble answering that: I couldn't understand that question. |
| 16 | group-by | What is the average resolution time per priority? | REFUSED | want 4 groups | I had trouble answering that: I couldn't understand that question. |
| 17 | group-by | How many resolved tickets per agent? | PASS | want 12 groups | 12 groups found. [12 rows] |
| 18 | filter | How many tickets have a customer rating of 1? | REFUSED | want 40 | I had trouble answering that: I couldn't understand that question. |
| 19 | filter | How many tickets have a resolution time over 48 hours? | REFUSED | want 56 | I had trouble answering that: I couldn't understand that question. |
| 20 | filter | How many high priority tickets are in the Technical category? | REFUSED | want 243 | I had trouble answering that: I couldn't understand that question. |
| 21 | filter | How many tickets have no customer rating? | REFUSED | want 47 | I had trouble answering that: I couldn't understand that question. |
| 22 | date range | How many tickets were created between 2026-01-01 and 2026-03-31? | REFUSED | want 486 | I had trouble answering that: I couldn't understand that question. |
| 23 | date range | How many tickets were created after 2026-09-01? | REFUSED | want 174 | I had trouble answering that: I couldn't understand that question. |
| 24 | date range | How many tickets were created before 2025-12-01? | REFUSED | want 333 | I had trouble answering that: I couldn't understand that question. |
| 25 | top agent | Which agent resolved the most tickets? | PASS | want AGT-05 / 185 | AGT-05 (Agent) has the most, with 185 tickets. |
| 26 | top agent | Which agent has the lowest average rating? | PASS | want AGT-08 / 3.14 | AGT-08 (Agent) has the lowest average, at 3.14. |
| 27 | top agent | Which agent has the highest average rating? | PASS | want AGT-12 / 4.63 | AGT-12 (Agent) has the highest average, at 4.63. |
| 28 | top category | Which category has the most tickets? | PASS | want Technical / 900 | Technical (Category) has the most, with 900 tickets. |
| 29 | top category | Which category has the most unresolved tickets? | REFUSED | want Technical / 22 | I had trouble answering that: I couldn't understand that question. |
| 30 | top category | Which category has the lowest average customer rating? | PASS | want Technical / 4.10 | Technical (Category) has the lowest average, at 4.10. |

## Per-question results: Ollama Cloud gpt-oss:120b-cloud

| # | Category | Question | Result | Gold | System answer |
|---|---|---|---|---|---|
| 1 | count | How many tickets are there in total? | PASS | want 2000 | 2000 tickets match this query. |
| 2 | count | How many tickets are unresolved? | PASS | want 47 | 47 tickets match this query. |
| 3 | count | How many tickets are open? | PASS | want 30 | 30 tickets match this query. |
| 4 | count | How many critical tickets are unresolved? | PASS | want 19 | 19 tickets match this query. |
| 5 | count | How many tickets are escalated? | PASS | want 17 | 17 tickets match this query. |
| 6 | count | How many resolved tickets are in the Billing category? | PASS | want 616 | 616 tickets match this query. |
| 7 | average | What is the average customer rating? | PASS | want 4.11 | The average customer rating is 4.11. |
| 8 | average | What is the average resolution time in hours? | PASS | want 11.08 | The average resolution time is 11.08. |
| 9 | average | What is the average response time in hours? | PASS | want 2.31 | The average response time is 2.31. |
| 10 | average | What is the average rating for Technical tickets? | PASS | want 4.10 | The average customer rating is 4.10. |
| 11 | average | What is the average resolution time for critical tickets? | PASS | want 5.90 | The average resolution time is 5.90. |
| 12 | group-by | How many tickets per priority? | PASS | want 4 groups | 4 groups found. [4 rows] |
| 13 | group-by | How many tickets per category? | PASS | want 3 groups | 3 groups found. [3 rows] |
| 14 | group-by | How many tickets per status? | PASS | want 3 groups | 3 groups found. [3 rows] |
| 15 | group-by | What is the average customer rating per category? | PASS | want 3 groups | 3 groups found. [3 rows] |
| 16 | group-by | What is the average resolution time per priority? | PASS | want 4 groups | 4 groups found. [4 rows] |
| 17 | group-by | How many resolved tickets per agent? | PASS | want 12 groups | 12 groups found. [12 rows] |
| 18 | filter | How many tickets have a customer rating of 1? | PASS | want 40 | 40 tickets match this query. |
| 19 | filter | How many tickets have a resolution time over 48 hours? | PASS | want 56 | 56 tickets match this query. |
| 20 | filter | How many high priority tickets are in the Technical category? | PASS | want 243 | 243 tickets match this query. |
| 21 | filter | How many tickets have no customer rating? | PASS | want 47 | 47 tickets match this query. |
| 22 | date range | How many tickets were created between 2026-01-01 and 2026-03-31? | PASS | want 486 | 486 tickets match this query. |
| 23 | date range | How many tickets were created after 2026-09-01? | PASS | want 174 | 174 tickets match this query. |
| 24 | date range | How many tickets were created before 2025-12-01? | PASS | want 333 | 333 tickets match this query. |
| 25 | top agent | Which agent resolved the most tickets? | PASS | want AGT-05 / 185 | AGT-05 (Agent) has the most, with 185 tickets. |
| 26 | top agent | Which agent has the lowest average rating? | PASS | want AGT-08 / 3.14 | AGT-08 (Agent) has the lowest average, at 3.14. |
| 27 | top agent | Which agent has the highest average rating? | PASS | want AGT-12 / 4.63 | AGT-12 (Agent) has the highest average, at 4.63. |
| 28 | top category | Which category has the most tickets? | PASS | want Technical / 900 | Technical (Category) has the most, with 900 tickets. |
| 29 | top category | Which category has the most unresolved tickets? | PASS | want Technical / 22 | Technical (Category) has the most, with 22 tickets. |
| 30 | top category | Which category has the lowest average customer rating? | PASS | want Technical / 4.10 | Technical (Category) has the lowest average, at 4.10. |
