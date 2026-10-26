# dev progress (40 questions, eval/dev.jsonl, judge_lite = keyword matching, rough)

| run | what | hit_any | hit_all | must_cover | must_full | latency, s |
|---|---|---|---|---|---|---|
| dev-base | code before tonight | 0.90 | 0.625 | 0.675 | 0.425 | 42 |
| dev-rules | + prompt rules (modality, regime), situation grazhdane, faith modality, prokat first | 0.90 | 0.575 | 0.642 | 0.350 | 40 |
| dev-multiq | + multi-query retrieval | 0.975 | 0.70 | 0.70 | 0.375 | 47 |
| dev-plan | + answer plan, must_say check, hedging | 0.95 | 0.625 | 0.725 | 0.475 | 75 |
| dev-head | + headline consistency check | 0.975 | 0.625 | 0.717 | 0.45 | 77 |
| dev-final | same + gk 191-193, 395 in corpus | 0.95 | 0.65 | 0.725 | 0.45 | 78 |

Noise on 40 questions is about +-5 points, so differences under 5 points mean nothing.
