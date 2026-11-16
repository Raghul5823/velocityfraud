# VelocityFraud: 60-minute technical session, full script

**Audience:** technical trainers who already know the big picture.
**Goal:** a clear, live, two-way session.
**The flow:** picture first, then reasons, then the live demo, then proof, then discussion.

## How to read this script

**What each label means:**
- **SHOW:** what is on screen.
- **CLICK:** a Demo Console step.
- **SAY:** your words. Use your own voice, but keep every fact and number exactly as written.
- **ASK:** a question to the audience. Wait 5–10 seconds. If nobody answers, give the answer line.
- **IF ASKED:** a short ready answer. All of them are collected at the end.

**Timing and numbering:**
- `[mm:ss]` is the time you should have reached when that slide starts.
- Slide numbers are the **new (version 4) deck order**, made by the update prompt.

## Before the session: restore and check (start 2–3 hours before)

1. **Restore the demo server.** In the Hetzner Console, go to Snapshots and open `vf-demo-after-demo-2026-11-10`. Click ⋯ → Create server, with these settings:
   - Type CPX32
   - Location Helsinki
   - SSH key hetzner-key
   - Firewall **vf-demo-fw**
   - Name `vf-demo`
2. **Restore the load server** the same way from `vf-loadgen-2026-11-10`, with these settings:
   - Type CPX22
   - Same key and firewall
   - Name `vf-loadgen`
3. **Update the Demo Console.** Open Settings, enter both new IPs and click **Save**. Then click **Forget old host key**, then **Test connection**.
4. **Restart the pipeline.** Run **R9 Full pipeline restart**, wait 3 minutes, then run **P1**. Every line must read OK.
5. **Prepare the rest:**
   - Run **P2** (tunnel), then **P3** (Power BI), then **P6** (load server). If P6 says k6 or Locust is missing, run **P5**.
   - **On the laptop:** run `docker compose -f infra/docker-compose.yml up -d` in the velocityfraud folder, so step 1.0 has its local services.
   - **Browser tabs:** open Kafka UI, MLflow, API docs (Swagger) and the Hetzner Console.
   - **Two Hetzner graph tabs, ready for Act 5:** Hetzner Console → **vf-demo → Graphs**, and in a second tab **vf-loadgen → Graphs**. In both, pick the **shortest time range** offered, so a one-minute spike is easy to see.
   - **Last of all:** Settings → **Clear step marks**.
6. **Save quota:** don't run Groq (3.1) or Gemini (2.5) while preparing.
7. **Deck:** type the real date over "[session date]" on slide 1.
8. **After the session:** delete both servers, and their IPs.

## Three habits for this session

1. **Picture first, then reasons, then proof.** Never explain a "why" before the audience has seen the "what".
2. **Say the number.** "56.69 milliseconds" is better than "very fast".
3. **Pause instead of filler.** Replace "as I said" and "this one" with a one-second pause.

**Names to say clearly:**

| Name | How to say it |
|---|---|
| XGBoost | X-G-Boost |
| Locust | LOH-kust |
| Hetzner | HETZ-ner |
| Qwen | chwen |
| Gemini | JEM-in-eye |
| SHAP | shap |
| idempotent | eye-dem-POH-tent |

---

# 1 · THE BIG PICTURE (00:00 – 07:00)

## [00:00] Slide 1: Title

**SHOW:** slide 1.

**SAY:**
> Good morning, and thank you for the time again.
> Today I'll take you through VelocityFraud end to end, and most of it you'll see running live, not on slides.
> I'd like this to be a discussion. Please stop me at any point. I've also kept a few questions for you along the way.

**[00:30] CLICK:** switch to the Demo Console and click **1.0**. Then come back to the slides.

**SAY (while clicking):**
> One thing before I start. I've just started our full automated test suite: all 122 tests. It runs on this laptop in the background while we talk, and we'll look at the result together in about forty-five minutes.

## [00:45] Slide 2: Agenda

**SAY:**
> Here's the hour.
> First the big picture, in two slides. Then why it's built this way. Then how one transaction gets its score.
> Then about half of the session is the live demo, on the cloud server.
> Then the proof, the roadmap, and your questions.

## [01:30] Slide 3: What is VelocityFraud

**SAY:**
> In one sentence: VelocityFraud is a real-time fraud detection pipeline. It decides on every card transaction in milliseconds, and it shows its reasons.
>
> Five verbs describe everything it does.
>
> **Stream.** Every transaction enters Kafka as a checked event. Card, IP and device are turned into SHA-256 tokens first, so no raw card data travels through the system.
>
> **Decide.** An XGBoost model scores it and returns ALLOW, REVIEW or BLOCK. Ninety-five out of a hundred decisions come back within 56.69 milliseconds, at 10,000 transactions a minute. That "95 out of 100" is what p95 means.
>
> **Explain.** For every REVIEW and BLOCK, SHAP shows the top five reasons, and a plain-English narrative is attached.
>
> **Review.** Doubtful cases go to a person, and a customer can appeal a block.
>
> **Learn.** The analyst's verdict goes back into Kafka as training data.
>
> Why the name? Velocity is what it delivers, decisions in milliseconds. It's also what it catches: velocity attacks, bursts of transactions on one card.

## [03:30] Slide 4: Architecture as built

**SAY:**
> Here is the same thing as a picture. Let's follow one transaction from left to right.
>
> **Stage one, ingest.** Our source data is the IEEE-CIS dataset: 590,540 real card transactions, 3.5% of them fraud. A replayer program sends them two per second, as if they were live payments. Card, IP and device are already tokenised.
>
> **Stage two, stream.** They land in Kafka.
> - It's version 3.7, in KRaft mode, so there's no separate ZooKeeper cluster to run.
> - Every event is an Avro record, a fixed and typed format.
> - A schema registry checks each one with BACKWARD compatibility, so a producer can never send something that breaks a consumer.
> - There are five topics: raw, scored, enriched, the Groq second opinion, and feedback.
>
> **Stage three, decide.** These dark boxes are the decision path.
> - Redis rules run first: a blocklist and a velocity rule.
> - Then XGBoost scores the transaction.
> - There are two scorers, a primary and a hot standby. If the primary dies, the standby takes over. In rehearsal that took 971 milliseconds.
>
> **Stage four, explain and advise.** Only flagged transactions come here.
> - SHAP explains the score.
> - DistilBERT, a small language model, checks whether the merchant name looks fake.
> - Gemini writes narratives.
> - Groq gives an independent second opinion.
> - Notice the dashed purple boxes: those are advisory. They can never decide a payment.
>
> **Stage five, store, see and act.**
> - Every decision is written once into PostgreSQL.
> - Power BI reads it through an encrypted SSH tunnel.
> - MLflow tracks the models.
> - Analyst verdicts and appeals go back to Kafka.
>
> All of this runs on one cloud server, a Hetzner machine with 4 CPUs and 8 GB. Only two ports are open: SSH, and the scoring API.

**ASK (check-in):**
> Before I go into *why* it's built like this: is the flow clear so far?

---

# 2 · WHY IT IS BUILT THIS WAY (07:00 – 13:00)

## [07:00] Slide 5: Six realities

**SAY:**
> Why does it look like this? Six facts about the problem shaped the design.
>
> **One: fraud is rare.**
> - Only 3.5% of transactions are fraud, about 1 in 29.
> - A model that never flags fraud would be 96.5% "accurate", and completely useless.
> - So we never use accuracy. We measure recall, which is how much fraud we catch, plus precision and ROC-AUC.
>
> **Two: latency is revenue.**
> - The decision sits in the middle of checkout. A slow "yes" loses the sale, just as fraud does.
> - That's why the decision is made by XGBoost running in memory, with a 100-millisecond budget. It is not a call to an external AI service.
>
> **Three: traffic spikes.** Think of a Diwali flash sale: five to ten times the normal traffic within minutes. Kafka absorbs the surge, and we load-tested at 10,000 transactions a minute.
>
> **Four: fraud has shapes.**
> - The shapes are a card-testing burst, impossible travel, a grocery customer suddenly paying a gambling merchant, and a fake-looking merchant name.
> - Each one needs its own signal: the velocity rule, SHAP, DistilBERT and the Gemini scenarios.
>
> **Five: a score is not a decision.** An analyst needs reasons, so every flag carries its top five reasons and a narrative.
>
> **Six: every service can fail.** So the rules fail open, the scorer has a hot standby, and nothing advisory can ever stop a payment.

## [10:00] Slide 6: Design decisions

**ASK first (before talking through the table):**
> A question for you. The RFP asks for an LLM, Groq, to score transactions in near real time. If you were designing this, would you put the LLM *inside* the payment decision, or *beside* it?

*(Wait for answers.)*

**SAY:**
> We put it beside. That's the first row.
> - In my original proposal, Groq was on the fast path. When I measured it, two things happened.
> - Each call took around 1.6 to 2.7 seconds in the earlier weeks.
> - The free tier, 200,000 tokens a day, ran out in 16 minutes at stream speed.
> - A payment can't wait for that. So XGBoost decides every payment, and Groq runs in parallel as a second opinion: 145 live calls in rehearsal, with zero failures.
>
> Three more decisions I'd highlight.
>
> **Three outcomes instead of two:** ALLOW, REVIEW and BLOCK. Doubt goes to a person instead of being declined, so fewer good customers are turned away. The trade-off is analyst workload.
>
> **Idempotent producers plus an upsert into PostgreSQL**, instead of full Kafka transactions.
> - Idempotent means that sending the same message twice has the same effect as sending it once.
> - We get the same result, no duplicates, with far less complexity. Across 4,692 exported events, there were zero duplicates.
>
> **Least exposure.**
> - Only two ports are open. Kafka UI, MLflow and the database are reached through an SSH tunnel.
> - Instead of rebuilding the server for each demo, I snapshot it and restore it: 20 to 30 minutes, instead of 2.5 to 3.5 hours.
>
> Every row has a trade-off column. I wanted each decision to say what it costs, not just what it gains.

---

# 3 · HOW ONE TRANSACTION GETS ITS SCORE (13:00 – 17:00)

## [13:00] Slide 7: 16 fields in, one decision out

**SAY:**
> Let's zoom into one transaction.
>
> At the top is the actual event: 16 fields covering who and when, the amount, the merchant, and the device and location. The tokens you see are 16-character SHA-256 hashes.
>
> Below are the six steps it goes through.
> 1. **It arrives** on the raw topic, and the blocklist checks it first.
> 2. **Featurise.** The scorer turns those 16 fields into the 43 inputs the model was trained on: the hour of day, the log of the amount, how common the email domain is, and so on. Any input the event can't supply is set to minus 999. *Keep that minus 999 in mind; it matters later.*
> 3. **The model is already in memory:** hundreds of decision trees, learned offline.
> 4. **Each tree adds a small value.** The total is called z.
> 5. **z becomes a score, and the score becomes a decision.**
> 6. **It is stored.** The event, plus seven new fields such as score, decision, model and timing, goes to the scored topic and into PostgreSQL.

## [15:00] Slide 8: Score to decision

**SAY:**
> This is the only formula in the talk. Score equals 1 over 1 plus e to the minus z. It's the sigmoid function.
> - Whatever total the trees produce, the sigmoid squeezes it into the range 0 to 1.
> - A bigger z means a higher score, which means more likely fraud.
> - The score is the model's probability of fraud.
>
> Two thresholds then turn the score into an action:
> - Below 0.50: ALLOW.
> - From 0.50 to 0.85: REVIEW, where a person looks at it.
> - 0.85 and above: BLOCK.
>
> The rules run first. A blocklisted card goes straight to 1.0.
>
> What does that give on the test set?
> - 83.9% of fraud caught.
> - 6.6% of good customers sent to a reviewer. Not declined, reviewed.
> - Only 0.7% of good customers hard-blocked.
>
> One honest note before the demo.
> - On the live stream today I use **demo thresholds**: REVIEW from 0.10, and BLOCK from 0.18.
> - Remember the minus 999? A single replayed event can't supply all 43 inputs, so live scores run lower.
> - With production thresholds, almost everything would be ALLOW, and you wouldn't see the other two paths.
> - After the demo I'll show you exactly how big that gap is, and the measured plan to close it.

---

# 4 · LIVE DEMO (17:00 – 45:00)

## [17:00] Slide 9: Demo map

**SAY:**
> Now the live system, in five acts:
> 1. The platform running.
> 2. Decisions and explanations.
> 3. AI oversight, and what happens when parts fail.
> 4. People in control.
> 5. Operations and quality, including a live load test.
>
> How do you know it's live? Every output carries the server clock. Counters grow between runs. And in Act 2, you will choose a transaction yourselves.

**SHOW:** switch to the Demo Console.

**SAY:**
> Everything runs from this console.
> - Each step is a catalogued script. There's no free typing of commands, so nothing gets mistyped live.
> - The left side is the step. The right side streams the output from the cloud server.

## Act 1 · The live platform [18:00 – 22:00]

**CLICK 1.1, then SHOW the Hetzner tab.**
> This is the cloud server: 4 CPUs and 8 GB.
> - Six containers: Kafka, PostgreSQL, Redis, the schema registry, Kafka UI and MLflow.
> - Nine pipeline programs: the API, two scorers, the Groq scorer, the slow path, the text checker, the sink, the replayer and the metrics collector.
>
> And here it is in the Hetzner console.

**CLICK 1.2, then SHOW the Kafka UI tab (Topics → transactions.raw → Messages).**
> These are the message counts per topic. The plus numbers show what arrived in the last ten seconds: that's live traffic.
>
> Below that is the schema registry: BACKWARD compatibility, five registered schemas. And a live test:
> - I try to register a breaking change, a new field with no default. The registry rejects it.
> - A safe change, with a default, is accepted.
> - That's what stops one team's change from breaking another team's consumer.
>
> In Kafka UI, these are the real messages. Notice the card token: there's no card number anywhere.

**CLICK 1.3, then SHOW Power BI: Real-time Alert Feed (Optimize → Refresh visuals).**
> These are the last five minutes of live decisions:
> - ALLOW, REVIEW and BLOCK.
> - The average score and average latency for each, around 30 milliseconds.
> - The throughput in the last minute.
>
> The same data is on the Power BI alert feed.

## Act 2 · Decisions in milliseconds, explained [22:00 – 28:00]

**CLICK 2.1.**
> Three fixed transactions go through the public scoring API.
> - A 25-dollar grocery purchase near home: ALLOW.
> - 899 dollars of electronics in Russia, 8,742 km away: REVIEW.
> - 1,500 dollars of electronics, 3,000 km away: BLOCK.
>
> Look at the response times: under twenty milliseconds.

**SHOW Swagger → POST /score → Try it out. Paste the BLOCK body from the run sheet.**
> Now it's your turn. Give me an amount and a country.

*(Change `amount`, `merchant_country` (two letters, e.g. US, GB, RU) and `geo_distance_km`. Give `event_id` and `card_token` a new value, then click Execute.)*

> Here are the score, the decision, and `scoring_latency_ms`, the time inside the API. Whatever you chose, the answer came back in milliseconds.

**CLICK 2.2.**
> Card testing. Fraudsters try tiny one-dollar charges first, to see whether a stolen card works. Here are six one-dollar charges on a brand-new card.
> - The model rates each one as low risk. It's just a dollar.
> - But the velocity rule counts charges per card in Redis: five a minute, twelve in ten minutes, twenty-five an hour.
> - On the fifth attempt, it escalates to REVIEW.
>
> A rule catches what the model alone misses.

**CLICK 2.3, then SHOW Power BI's narrative column.**
> Every flagged event is explained.
> - These are the latest flagged transactions, each with its top SHAP feature, and one full explanation.
> - SHAP shows how much each input pushed this score up or down.
> - Where you see "missing on live event", that's the minus 999. SHAP is honest: it shows the model leaning on what's missing. That's exactly the gap the roadmap closes.
>
> On the live stream, the narrative comes from a template, because it has to be ready within 1.5 seconds. Gemini writes the richer narratives, which you'll see in step 2.5.

**CLICK 2.4.**
> This is a language model reading merchant names. DistilBERT scores how unnatural a name reads.
> - gmail.com scores low.
> - verify-account-now.info crosses our 6.0 threshold and is flagged.
> - The threshold is deliberately conservative, so that real merchants aren't flagged. A look-alike check, for names like paypal written with a capital I, is a next step.
>
> It runs on our own server: no API cost, and no data leaves.

**CLICK 2.5 (confirm it; it uses about 3 Gemini calls).**
> Three classic fraud patterns: velocity, impossible travel, and a merchant-category mismatch.
> - Each one is scored by XGBoost, explained by SHAP, and written up in plain English by Gemini.
> - This is what an analyst reads, instead of a table of features.

## Act 3 · Independent AI oversight and resilience [28:00 – 34:00]

*Run 3.1 → 3.2 → 3.3 straight after each other.*

**CLICK 3.1.**
> Now an independent second opinion. Groq runs a language model, Qwen, on the same tokenised events, limited to 12 calls a minute. Each call returns a score and a written reason.

**CLICK 3.2, then SHOW Power BI: Operational Health.**
> Both opinions side by side on the same events: XGBoost's decision, Groq's decision, the latencies, and Groq's reasoning.
> - XGBoost answers in milliseconds. Groq takes hundreds of milliseconds.
> - They don't always agree, and that disagreement is useful, as you'll see in a moment.

**CLICK 3.3.**
> Now I remove the LLM completely. Groq is stopped, and the decisions keep flowing: the scored count is still going up. Nothing in the payment path depends on it.

**CLICK 3.4.**
> Now something harsher: I stop the scorer that's currently deciding.
> - The standby checks a Redis lock every second.
> - Watch: "leadership moved to standby in…" so many milliseconds.
> - There's no gap in the scored stream.

**CLICK 3.5.**
> And self-healing. The stopped scorer comes back as the new standby, so we're fully redundant again.

**CLICK 3.6.**
> Finally, the drift monitor. If XGBoost and Groq disagree on more than 5% of events, something has drifted, and an alarm fires.
> - It fires today. In rehearsal, the disagreement was 68.3%.
> - That's the monitor working as designed. It's telling us the live inputs differ from training: the same gap I mentioned earlier.
> - Every check is logged for audit.

**ASK (check-in):**
> That was the resilience part. Is there a failure you'd have expected me to test that I didn't?

## Act 4 · Humans in control [34:00 – 37:00]

**CLICK 4.1.**
> People stay in control. A customer disputes a blocked payment, and the appeal is recorded.

**CLICK 4.2.**
> An analyst reviews it and overturns the block.
> - The card is whitelisted for 24 hours.
> - The full audit trail is stored: who, when and why.
> - The model's score itself doesn't change. The analyst's decision is the binding outcome.

**CLICK 4.3.**
> And the learning loop. The analyst's verdict, "legitimate customer, false positive", goes to the Kafka feedback topic as training data. A view tracks how often the model and the analysts agree.

## Act 5 · Operate, govern, scale [37:00 – 45:00]

**CLICK 5.1, then SHOW Power BI: Operational Health.**
> This is what an on-call engineer watches:
> - The consumer lag for every service.
> - Groq's rate-limit headroom.
> - The fast-path latency at p50, p95 and p99 for the last 15 minutes.

**CLICK 5.2, then SHOW the MLflow tab.**
> Model governance. Both models were trained on the same data and logged in MLflow. XGBoost is the champion, and in a few minutes I'll show you why, on a slide.

**CLICK 5.3, then SHOW the vf-demo → Graphs tab (this is the "before" picture).**
> The whole platform runs on one 4-CPU server, at about 6.7 US cents an hour while it's running.
>
> Look at these graphs: CPU and network are low and steady. That's the whole live pipeline at two transactions a second. Remember this picture; in a minute we'll hit it with 10,000 a minute.

*Point at: **CPU** (low, flat line) and **Network** (small, flat traffic).*

**SHOW slide 10 (How the live load test works), for about 30 seconds.**
> Now the load test from week 15, repeated live.
> - A separate small server, the load server, sends 167 transactions a second to the scoring API. That's 10,000 a minute, for sixty seconds.
> - Why a separate server? If the load generator ran on the same machine, it would take CPU away from the scorer, and we'd be measuring that, not the system.
> - Every request uses a new card, so every one runs the full model. No shortcuts.

**CLICK 5.4 (confirm). It runs for about 75 seconds: 60 seconds of load plus the summary. Don't press Stop.**

*What it touches:* only the scoring API, which scores with XGBoost. **No Groq, no Gemini, no quota.** It writes nothing to the database or Kafka, so Power BI and the live counts are unaffected. The demo server is just busier for that one minute.

*While it runs:*
> Every ten seconds you'll see it ticking. The week-15 certificate ran this same rate for thirty minutes, and its p95 was 56.69 milliseconds.

*When it finishes:*
> Here's the result. p95 is ___ milliseconds against a 100-millisecond budget, with ___ percent failed.

*Read the numbers from the screen.*

**SHOW the Hetzner graphs (the "after" picture).** If the spike isn't drawn yet, refresh the tab once; Hetzner draws its graphs with a short delay.

1. **vf-demo → Graphs:**
   - **CPU** jumps up for about one minute, then drops back.
   - **Network: incoming** traffic jumps at the same minute.
   > This is the demo server receiving 10,000 transactions a minute and scoring every one with the model, then going straight back to normal.
2. **vf-loadgen → Graphs:**
   - **CPU** and **Network: outgoing** jump at exactly the same minute.
   > And this is the load server sending them. Same minute, two servers. That's independent proof from the cloud provider that the load was real.

**CLICK 5.5 (confirm). It runs for about 75 seconds. Don't press Stop.** Like 5.4, it uses no LLM and writes nothing to the database.
> k6 tested speed, at the target rate. Locust tests capacity: a hundred simulated payment gateways sending as fast as they can.

*When it finishes:*
> That's ___ a minute, against the 10,000 target, with ___ failures. Response times are higher here by design: at full capacity, requests queue up. The speed figure is the one from k6.

**SHOW vf-demo → Graphs again** (refresh once).
- A **second spike**, usually **taller than the first**, because Locust pushes as fast as the server can answer.
> Two spikes: the first is the target rate, the second is full capacity. Both times, zero failures, and the server drops straight back to its normal line.

**CLICK 5.6.**
> Here are seven quality rules from our test suite, run right now on the last hour of live decisions:
> 1. The stream is flowing.
> 2. There are no duplicates.
> 3. Every event is fully decided.
> 4. Every decision follows the policy.
> 5. Decisions stay within the 100-millisecond budget.
> 6. Every flag is explained.
> 7. No raw card or IP data is stored.
>
> Seven out of seven.

**CLICK 5.8.**
> And the test suite I started in the first minute: all 122 tests.
> - 58 are unit tests.
> - 64 are integration tests, run against a local copy of Redis, PostgreSQL and Kafka.
>
> The result is ___.
>
> Why run them on the laptop? The integration tests write test records and take the failover lock. You never run those against a live system.

*(Skip 5.7. Slide 12 covers the recorded evidence.)*

---

# 5 · PROOF AND QUALITY (45:00 – 52:00)

## [45:00] Slide 11: Results in six numbers

**SAY:**
> So, in six numbers:
> - **56.69 milliseconds** at p95, at 10,000 transactions a minute.
> - **83.9%** of fraud caught on the held-out test set. That's 521,608 dollars of the 639,135.
> - **0.7%** of good customers hard-blocked. The other doubtful cases go to a person.
> - **971 milliseconds** for the standby to take over.
> - **122 tests**, at 80.05% coverage.
> - **Zero rupees** for every AI and ML tool. The cloud server is the only bill.

## [46:30] Slide 12: Quality you saw live

**SAY:**
> The left side is what you just watched, next to the week-15 certificate.
> - Same rate, same budget, and zero failures in both.
> - p95 was within a few milliseconds of the certificate.
> - p99 is higher today for two reasons. Every request now also runs the velocity rule and the score-cache check. And this server is running the whole live pipeline at the same time. It's still inside its 200-millisecond budget.
>
> The right side is the seven live checks.
>
> The bottom strip separates what you saw live from what is recorded evidence: coverage, the 59 data checks, and the 16-report audit.

## [48:00] Slide 13: XGBoost vs Random Forest

**SAY:**
> Why XGBoost? Both models used the same 43 features, and both were tested on the same 118,108 held-out transactions.
> - **ROC-AUC** measures how well a model ranks fraud above genuine transactions. 0.5 is a coin flip; 1.0 is perfect.
> - Random Forest is more **precise**: it raises fewer false alarms.
> - XGBoost **catches more fraud**: a recall of 0.839 against 0.778, plus a higher ROC-AUC and PR-AUC.
> - In fraud, a missed fraud costs money, while a review costs a few minutes of an analyst's time. So we chose recall.
> - The price is a false-positive rate of 6.56%. Those cases go to a person, not to a decline.
>
> The right side is the **out-of-time test**: train on earlier days, test on later days. ROC-AUC is 0.889. That's the honest, production-like number, and we now report it alongside the headline.

## [49:30] Slide 14: The next measured step

**SAY:**
> Now the gap I promised to measure.
> - Offline, the model scores 0.956. On the live replay stream it scores 0.574, with the same model file on the same 118,108 transactions.
> - The model isn't wrong. It's being fed less than it learned from. Of the 43 inputs, only 7 match training exactly on a live event. The rest are minus 999, or encoded differently.
>
> So we measured the fix instead of guessing:
> - **Phase 1**, nine code fixes: 0.660.
> - **Phase 2**, seventeen optional fields added to the event: 0.783.
> - **Phase 3**, a feature store holding each card's history: back into the 0.889 to 0.956 range.
>
> Until each phase passes the gates, live flags go to an analyst. Safety first.
>
> I ran this audit read-only, with Evidently, an open-source tool: sixteen reports.

## [51:30] Slide 15: Quality gates (keep it short)

**SAY:**
> These are the four release gates: ROC-AUC, recall, false-positive rate and precision. The champion clears all four. From now on, every model or feature change has to clear them too.

---

# 6 · ROADMAP AND THE ASK (52:00 – 55:00)

## [52:00] Slide 16: Roadmap

**SAY:**
> Each phase feeds the model more of what it learned from.
> - **Today**, 7 of the 43 inputs match, and 16.8% of fraud is caught at the same alert budget.
> - **Phase 1** is code only: 14 inputs and 23.4%.
> - **Phase 2** adds optional fields, which is a BACKWARD-compatible change: 33 inputs and 41.5%.
> - **Phase 3**, the feature store: all 43, and up to 83.9%.
>
> The exit rule for every phase is the same: all four gates pass, and the thresholds are re-calibrated.

## [53:30] Slide 17: Summary and the ask

**SAY:**
> To sum up:
> - Speed: under 100 milliseconds, proven for thirty minutes and again live.
> - Accuracy: validated, with 83.9% caught and 0.7% hard-blocked.
> - Explanations on every flag, resilience with a 971-millisecond failover, quality with 122 tests and a 16-report audit.
> - All within the budget.
>
> The ask: approve phase 1. That's nine live-feature fixes, each one re-measured against the four gates.

---

# 7 · DISCUSSION (55:00 – 60:00)

## [55:00] Slide 18: Let's discuss

**SAY:**
> I'd like to hear from you. Three questions.

Use whichever one gets the room talking. Your view is below each question.

**1. "Phase 1 next, or straight to the feature store?"**
> My view: phase 1 first. It's code only, it's cheap, and it's measurable in days. The feature store is the biggest gain, but it needs new infrastructure.

**2. "Which failure or attack should we test next?"**
> My view: account takeover, meaning a real card on a new device. And a Kafka broker failure during peak load.

**3. "What would a Psiog client need before this goes to production?"**
> My view: the feature store, threshold re-calibration on their own data, and their compliance sign-off on how the tokens are handled.

## [60:00] Slide 19: Thank you

**SAY:**
> Thank you. The code, the reports and every number you saw are in the evidence index. I'm happy to go deeper on any part.

---

## If you are short of time

Cut these, in this order:
1. Slide 15 (gates).
2. Step 2.4.
3. Step 5.3.
4. In Act 4, run only 4.2.
5. Slide 16, which you can cover in one sentence on slide 17.

---

## IF A STEP FAILS: what you see, what to do, what to say

### The four rules during the live demo

1. **One fix, about one minute.** Try the fix in the table once. If it doesn't work, say the line, move on, and come back to it in Q&A.
2. **Never type commands live.** Every fix below is a console step (P, R or an Act step), a browser refresh, or a double-click.
3. **Read the red line out loud, calmly.** The console prints what failed in plain words. A live system that recovers in front of the audience is a strength, not a weakness.
4. **The backup slides are your safety net.** Each failure below names the slide to show if the live step can't run.

**One line that fits any failure:**
> This is a live system, so let me show you how we recover from that.

### Any step: general failures

| You see | Do this | Say |
|---|---|---|
| "[FAIL] SSH connection failed…" | Check the laptop's internet. Open Settings → **Test connection**. If it mentions "REMOTE HOST IDENTIFICATION HAS CHANGED": **Forget old host key**, then Test connection again. | "The laptop lost its link to the cloud server for a moment; reconnecting." |
| "[FAIL] The pipeline is not running on the server…" | Run **R9**, wait 3 minutes, run **P1**. During the demo, go to the next slides meanwhile. | "One service stopped; the full restart brings everything back in about 90 seconds." |
| "The step was stopped after its … s time limit" | Run the step **once** more. If it fails again, run **P1** to see which part is down. | "That took longer than its safety limit; running it again." |
| "'…' is still running" | Wait for that step to finish, or press **Stop**. | — |
| The console page is blank or frozen | Refresh the browser tab (it reconnects to the running step). If the black console window was closed, run **Start Demo Console.cmd** again. | — |
| No internet at all | Switch the laptop to your **phone hotspot**. The tunnel window reconnects by itself. | "Switching networks; the cloud server keeps running regardless." |
| The whole server is down (nothing reachable) | Check **vf-demo** in the Hetzner Console: if it is off, **Power on**, then **R9 → P1**. If Hetzner itself is down, finish on slides: **12**, **B19**, **A5**. | "The cloud provider is having an issue. Here are the measured results from our rehearsals." |

### Pre-flight P1–P6 (before the audience joins)

**P1 Readiness check:** match each FAIL or WARN line to its fix.

| P1 line says | Do this |
|---|---|
| A container (vf-kafka, vf-postgres, vf-redis…) is missing or not running | **R9**, wait 3 min, **P1** |
| "tmux session 'vf' not found" | **R9**, wait 3 min, **P1** |
| "api: stopped / window missing" | **R3**. If the header still says "Scoring API online", an old API process from before a restart is holding port 8000; R3 now stops it first ("Port 8000 is free"), then starts the API. Then **P1** again. |
| "slowpath: stopped" | **R4** |
| "text: stopped" | **R5** |
| "sink: stopped" | **R6** |
| "replayer: stopped" | **R7** |
| "ops: stopped" | **R8** |
| "primary" or "standby: stopped", or "No scorer holds the leader lock" | **R9**, wait 3 min, **P1** |
| "API is not answering on port 8000" or "Model not loaded" | **R3** |
| "API cannot reach Redis" | **R9** |
| "Thresholds are … (expected 0.1 / 0.18)" | **R3** (it restarts the API with the demo thresholds) |
| "No events scored in the last 3 minutes" | **R7**; if still none after 1 min, **R9** |
| WARN "No enriched events in the last 10 minutes" | **R4**, wait 2 min, **P1** |
| WARN "Ops metrics are …s old" | **R8** |
| WARN "High lag: …" | Normal for 2–3 minutes after a restart. Wait, then **P1** again. |
| WARN "Registry shows rule … run R10" | **R10** |
| WARN "MLflow API not reachable" | **R9** if there is time; otherwise show Power BI Model Performance in step 5.2 |

**P2 Secure tunnel:** this is the one that failed on 6 Nov.

| You see | Do this |
|---|---|
| Any P2 failure, or Power BI says "actively refused it" | 1. Close the old window "VelocityFraud - secure tunnel (keep open)". 2. Press **Windows + R**, paste `"%USERPROFILE%\Desktop\VF Tunnel.cmd"`, press Enter, minimise it. 3. Wait 5 s until "Secure tunnel open" is green. 4. Click **P2**: it now says "already open". |
| "A partial tunnel is open" | An old tunnel window still holds a port. Close it, wait 5 s, click **P2** again. |
| The VF Tunnel window keeps printing "reconnecting" | Check the internet, then Settings → **Test connection**. If the host-key message appears: **Forget old host key**. |

**P3 Power BI:**

| You see | Do this |
|---|---|
| "Power BI file not found" | Open it by hand: Documents → Fraud Detection → **Fraud_Detection_Dashboard_Cloud.pbix**. |
| "[WARN] The tunnel is not open" | Fix the tunnel first (P2 row above). |
| An error dialog after refreshing | You pressed Home → Refresh. Close the dialog and use **Optimize → Refresh visuals** only. |
| Visuals show "actively refused it" | The tunnel dropped: see P2. |

**P4 Groq check:**

| You see | Do this |
|---|---|
| "Groq is already running" | Run **R2**, then P4 again. |
| "Groq did not score an event within 45 s" | Usually the free-tier quota (429). Don't retry. Groq is advisory: Act 3 still works from 3.3 on. |
| "Groq did not stop within 20 s" | **R2** |
| "tmux window 'groq' is missing" | **R9**, wait 3 min, **P1** |

**P5 / P6 Load server:**

| You see | Do this |
|---|---|
| P5: "apt-get could not…", "Could not download the k6 signing key", "installation failed" | Hetzner's download mirror is busy. Wait 5 minutes and run **P5** again. |
| P6: "k6 is not installed" or "Locust is not installed" | Run **P5** (2–4 minutes). |
| P6: "The scoring API on the demo server is not answering" | Run **P1** on the demo server first; then P6. |
| P6: "The demo server IP is not set" or SSH fails | Settings: check **both** IPs (demo `<server-ip>`, load `<loadgen-ip>`), Save, Test connection. |

### Act 1

| Step and what you see | Do this | Say |
|---|---|---|
| **1.0** "The local test services are not running" | Start **Docker Desktop**, run `docker compose -f infra/docker-compose.yml up -d` in PowerShell in the velocityfraud folder, wait 1 min, click **1.0** again. If there's no time: skip 1.0 and 5.8. | "The test suite needs its local services; I'll show the recorded result instead: 122 passed." |
| **1.1** a program shows MISSING or stopped | Use the matching R step from the P1 table (R3–R8). | "One program is down; this is exactly what the recovery steps are for." |
| **1.2** "Could not read topic offsets from Kafka" | **R9** (about 3 min). Move on to 1.3's slide content meanwhile, then run 1.2 again. | "Kafka is restarting; the scored history stays in the database." |
| **1.2** registry FAIL or "none - run Recovery > R10" | **R10**, then **1.2** again. | "The registry keeps its rules in memory; this step re-applies them from Git." |
| **1.2** Kafka UI tab won't load | Tunnel: see the P2 table. | — |
| **1.3** empty table, or throughput 0 | **R7** (replayer), wait 30 s, **1.3** again. | "The traffic generator paused; restarting it." |

### Act 2

| Step and what you see | Do this | Say |
|---|---|---|
| **2.1 / 2.2** "no valid response from the API" | **R3**, wait 15 s, run the step again. | "The scoring API is restarting; it takes about ten seconds." |
| **2.1** "[WARN]" (the decision differs from the expected one) | Run **P1** after the demo to check the thresholds; during the demo, carry on. | "The expected decision is printed next to the live one; the model scored it slightly differently." |
| **2.1** Swagger page won't load | Check the "Scoring API online" pill. If red: **R3**. If green, the office network may block port 8000: skip Swagger and use 2.1's output. | "Let's use the console's three transactions instead." |
| **2.2** no attempt says "VELOCITY RULE" | Redis is down and the rule failed open (by design). Run **P1** after the demo. | "If Redis is unavailable the rule fails open, so payments are never blocked by an outage; that's by design." |
| **2.3** "No enriched events yet" | **R4**, wait 1 min, **2.3** again. | "The explanation service is restarting; it catches up from Kafka without losing events." |
| **2.4** the text check shows "pending" | Wait 10 s and run again. If it stays: **R5**. | — |
| **2.5** the label says GEMINI_CACHED or TEMPLATE | Nothing. Don't run it again (quota). | "Gemini's free tier hit its limit, so the fallback chain worked: live Gemini, then the 24-hour cache, then the template. Never a blank." |

### Act 3

| Step and what you see | Do this | Say |
|---|---|---|
| **3.1** "Groq did not score an event within 45 s" | Don't retry. Go to **3.3** and **3.4**. | "Groq's free tier is rate-limited today. That's the point: payments don't wait for it." |
| **3.1** "tmux window 'groq' is missing" | Skip 3.1–3.3, go to **3.4**. Run **R9** after the session. | Same line as above. |
| **3.2** "[WARN] Groq is not running now" | Nothing: it shows the comparisons stored in the last hour. | "These are the stored comparisons from the last hour." |
| **3.3** "Groq did not stop within 20 s" | **R2**. | "It is finishing its current batch; forcing the stop." |
| **3.3** "No XGBoost decisions in the last 15 s" | Run **P1** after Act 3. | — |
| **3.4** "No scorer holds the leader lock" or "the standby did not take over" | Skip to **3.6**; run **R9** in Q&A or after the session. Show **B14** and **B19**. | "In rehearsal the takeover took 971 milliseconds; here's the record." |
| **3.4** "the lock names X as ACTIVE but that program is not running" | Run **3.5**. | "The standby is restarting the stopped scorer." |
| **3.5** "exited" or "window missing" | Carry on; run **R9** after the session. | "The standby keeps scoring; full redundancy returns with the next restart." |
| **3.6** "[WARN] Small sample" | Nothing: it widens its window by itself. | "Groq ran only briefly, so the check looks back further; it says so." |

### Act 4

| Step and what you see | Do this | Say |
|---|---|---|
| **4.1** "No un-appealed BLOCK decision found yet" | Wait 30–60 s (new BLOCKs arrive every minute), then **4.1** again. | "We need a fresh blocked payment to appeal; one arrives within a minute." |
| **4.2** "There is no open appeal" | Run **4.1** first, then **4.2**. | — |
| **4.3** "No blocked transaction without feedback found yet" | Wait 30–60 s, then **4.3** again. | Same as 4.1. |

### Act 5

| Step and what you see | Do this | Say |
|---|---|---|
| **5.1** high lag, or Groq headroom 0 | Nothing: after a restart, lag settles in 2–3 minutes; Groq reads 0 when it's stopped. | "Lag is draining after the restart; Groq is off, so it uses nothing." |
| **5.2** "MLflow API not reachable" or "No MLflow runs" | Show Power BI **Model Performance**, then slide **13**. | "The same metrics are on this page and on the next slide." |
| **5.4** "k6 is not installed" or SSH to the load server fails | Skip to slide **12** and **A5**. Run **P5/P6** after the session. | "Here is the same test from this week's rehearsal: 10,020 requests, 0 failed, p95 60.37 ms." |
| **5.4** "k6 did not finish" | Skip to slide **12**. | Same as above. |
| **5.4** "[WARN]" on p95 or p99 | Read the number out. | "This server is running the whole live pipeline at the same time; the 30-minute certificate stands at 56.69 ms." |
| **5.5** "Locust did not finish" or SSH fails | Skip to slide **12**. | "The rehearsal result: about 15,225 a minute, zero failures." |
| **5.6** "No scored events in the last 60 minutes" | **R7**, then **P1** after the session. | "The traffic generator paused; the checks need live data." |
| **5.6** "[WARN] Every flag explained" | Nothing. | "The explanation service is still catching up after the load test." |
| **5.6** "[WARN] Within the 100 ms budget" | Nothing. | "That window includes the load test you just watched." |
| **5.8** "Still running" | Click **5.8** again in a minute. | "It's on the last tests; we'll check back in a minute." |
| **5.8** "No test run yet" | Show slide **11** and **B20**. | "The recorded run: 122 passed." |
| **5.8** "[WARN] … skipped" | Show **B20**. | "Some integration tests skipped because a local service was down; the recorded full run is 122 passed." |
| **5.8** "stopped without a result" | Show **B20**. | Same as above. |

### Recovery steps R1–R10

| You see | Do this |
|---|---|
| **R1** (live program view): you pressed Ctrl+C in a tab | That program stopped. Leave with **Ctrl+b then d**, then run its R step (R3–R8). |
| **R2** "Groq did not stop within 20 s" | Run **R2** once more. If it still fails, **R9**. |
| **R3** "[Errno 98] Address already in use" | An old API process holds port 8000. Run **R3** again: it frees the port, then starts the API. If it says "Port 8000 is still held", run **R9**. |
| **R3–R8** "did not stop within 25 s" | **R9**, wait 3 min, **P1**. |
| **R3–R8** "tmux session 'vf' is missing" | **R9**, wait 3 min, **P1**. |
| **R3–R8** "… exited - see the output above" | Read the last lines. Then **R9**, wait 3 min, **P1**. |
| **R9** "Registry setup incomplete" or "Schema registry not answering yet" | Wait 1 minute, then **R10**. |
| **R9** SSH fails | The server may be off: Hetzner Console → vf-demo → **Power on**, wait 1 min, then **R9**. |
| **R10** "Schema registry (Apicurio) is not answering on port 8080" | **R9**, wait 3 min, then **R10**. |

---

## IF ASKED: answer bank

1. **"The proposal promised F1 ≥ 0.92."**
   - That was a stretch target, set before I had measured the data.
   - A 1,500-point threshold sweep shows this dataset's best possible F1 is about 0.67.
   - So I optimised for what the business needs, which is catching fraud: 83.9% recall and a ROC-AUC of 0.956. Doubtful cases go to review.
2. **"An FPR of 6.56% is high; why not 2%?"**
   - A 2% rate would miss 509 more frauds.
   - The 6.56% go to a reviewer, not to a decline. Only 0.7% of good customers are hard-blocked.
3. **"Why only 0.574 live?"** See slide 14.
   - The model is proven: 0.956 offline and 0.889 out-of-time.
   - The live event supplies only 7 of the 43 inputs exactly.
   - We measured the fix: 0.660, then 0.783, then the feature store.
4. **"Why isn't Groq the decision-maker?"**
   - It took 1.6 to 2.7 seconds per call in the earlier weeks, and the free tier ran out in 16 minutes at stream speed.
   - It's a parallel second opinion. Step 3.3 proves that payments never wait for it.
5. **"Why the demo thresholds?"**
   - Live scores run lower, because the events are lighter.
   - 0.10 and 0.18 let all three outcomes appear. Production is 0.50 and 0.85, and I disclose that up front.
6. **"Is it exactly-once?"**
   - Idempotent producers plus an upsert on event_id give the same no-duplicate result, and 4,692 exported events had zero duplicates.
   - read_committed on its own does nothing without transactions.
7. **"Why not Databricks for training?"**
   - Training runs locally, logged in MLflow, so training and serving share one environment.
   - The Databricks Free Edition runs a batch enrichment notebook.
8. **"Were Random Forest and XGBoost mandatory?"** Yes. The RFP's final review asks for both to be compared in MLflow, with the false-positive rate documented.
9. **"Why Kafka, and not Redis or a queue?"**
   - Kafka is a durable, ordered, replayable log. Several services (the scorer, Groq, the sink) read the same stream independently through consumer groups.
   - Redis is used here for fast lookups: the blocklist, the velocity counters, the score cache and the failover lock.
10. **"How do partitions work?"**
    - A topic is split into partitions. Each partition is an ordered log.
    - The consumers in a group share the partitions, so the processing scales out.
11. **"Does the stream use the velocity rule?"**
    - The velocity rule and the score cache run in the scoring-API path, which is what step 2.2 shows.
    - The hot-standby stream scorers apply the blocklist and XGBoost. Adding the velocity rule there is a small change.
12. **"Why is p99 higher than in week 15?"**
    - There are two extra Redis checks per request, and the whole live pipeline shares the server.
    - It's still within 200 ms, and p95 matches the certificate.
13. **"Why is the Locust result lower than in week 15?"** The same two reasons, and one minute instead of three. It's still above the 10,000-a-minute target, with zero errors.
14. **"Why run the tests on the laptop?"** The integration tests write records, add blocklist entries and take the failover lock. A local copy of the services proves the same code without touching the live system.
15. **"LLMs are random. How can you trust them?"**
    - The LLM never decides, so its randomness can't change a payment.
    - The drift monitor measures its disagreement.
    - Gemini's narratives are graded by a second model, and are dropped if SHAP doesn't support them.
16. **"What did it cost?"**
    - Every AI and ML tool is free tier or open source. The cloud is the only bill.
    - November: USD 11.25 (about ₹960). Check the Usage page on the day.
    - Week 15: USD 0.28.
    - All within the ₹2,500 ceiling. The servers are snapshotted and deleted when they're not in use.
    - If asked "why above the ₹800 estimate?": the live demo needed two rehearsals and a second load server, and the servers stayed up a few extra days. It's still well inside the ceiling, and backup slide B11 shows it to scale.
17. **"Why Hetzner?"** Reliable x86 provisioning (the proposal's ARM capacity wasn't available), hourly billing, a simple firewall, and a snapshot restore in 20 to 30 minutes.
18. **"Can the tokens be reversed?"**
    - No. They're salted SHA-256 hashes.
    - They're deterministic, so the same card always gives the same token. That's what the velocity rule needs.
19. **"What is KRaft?"** Kafka managing its own metadata, so there's no ZooKeeper cluster to run.
20. **"Why does the drift alarm fire?"**
    - It measures how often the two AIs disagree.
    - Today it's high because the live inputs are lighter than in training. That's the same gap the roadmap closes.
21. **"Model–analyst agreement shows 0%?"** The feedback so far comes from disputed cases, meaning overturns, so it measures disputes, not accuracy.
22. **"What's the score cache?"**
    - If an identical request arrives within one minute, it reuses its score.
    - Our own end-to-end tests caught a defect where every transaction got the same cache key. It's fixed, and it's in the proof-of-improvement backup slide.

---

## Backup jump map: which slide to open for a question

The main talk ends at slide 19. Everything after it is only for questions.

**How to jump:**
- **PowerPoint slideshow:** type the slide number and press Enter.
- **PDF in full screen:** press Ctrl+Shift+N and type the page number.
- **When you've answered:** jump back to slide 18 or 19.

| If they ask about… | Open |
|---|---|
| The business problem, the cost of errors | B1, B2, B3 |
| A simpler picture of the solution | B4 |
| Were all the RFP deliverables met? | B5 |
| Where is each requirement proven? | B7 |
| Stakeholders, the business-analyst view | B6 |
| One transaction's timeline, end to end | B8 |
| What changed from the proposal? | B9 |
| Best practices | B10 |
| Security, firewall, cost | B11, then A4 |
| Layer by layer | B12 (map) |
| Kafka, Avro, duplicates, exactly-once | B13 |
| Velocity rule, cache, failover, failure modes | B14 |
| SHAP, narratives, DistilBERT | B15 |
| Groq, drift alarm | B16 |
| PostgreSQL, Power BI, appeals, feedback loop | B17 |
| Bugs found, the F1 target, the self-audit | B18 |
| Rehearsal results | B19 |
| Test strategy, the test pyramid | B20 |
| The independent audit | B21 |
| How the week went, challenges solved | B22 |
| Lessons learned | B23 |
| Full metrics, confusion matrix, out-of-time | A1 |
| What a term means | A2 |
| Which report proves something | A3 |
| Tech stack and cost | A4 |
| How the load test was done | A5 |
