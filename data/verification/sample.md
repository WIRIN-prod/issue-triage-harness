# Verification sample

Label each issue against `docs/rubric.md`. Fill in the matching line in
`human-labels.jsonl`. Gold labels are withheld on purpose — seeing them first would
turn this into agreement-by-anchoring.

Set `disputed: true` only where the rubric genuinely underdetermines the answer,
not merely where the issue is low quality.

## #34727
**[Docs]: REDIS_URL prod warning is stale; the perf gap it cites is fixed**

### What happened? The caching docs still advise against `REDIS_URL` in production on performance grounds: > we **don't** recommend using REDIS_URL in prod. We've noticed a performance difference between using it vs. redis_host, port, etc. That guidance was correct when it was written, and it traces back to #3188. The cause was connection churn: the url path discarded the shared pool and opened roughly two new connections per request, which is ruinous over TLS because each one pays a fresh handshake. Current code pools correctly, and the gap is gone. Measured against a local redis behind a TCP relay injecting a fixed one-way delay, with redis in the request path on every call (response cachi…

<https://github.com/BerriAI/litellm/issues/34727>

## #34895
**NOT WORKING LITELLM**

PLESE HELP

<https://github.com/BerriAI/litellm/issues/34895>

## #35023
**[Bug]: CJK characters from concurrent requests bleed into unrelated streams (cross-request contamination in streaming)**

## Bug: CJK characters from concurrent requests bleed into unrelated streams (cross-request contamination) **Affected:** Confirmed in LiteLLM v1.93.0 and v1.94.0. NOT a regression of the v1.94.0 upgrade. ## Summary When reasoning-capable models stream through the LiteLLM gateway, Chinese (CJK) characters occasionally appear injected mid-token inside unrelated response streams. The injected words (`壁纸` = wallpaper, `起床` = get up, `信仰` = faith) do NOT appear anywhere in the request or in the model's actual response. They are fragments of Chinese text leaking across request boundaries inside the gateway. ## Actual behavior (evidence) Three independent confirmations across two different LiteLLM …

<https://github.com/BerriAI/litellm/issues/35023>

## #35084
**[Bug]: Incomplete documentation on pure litellm_config.yaml based setup for proxy server**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### What happened? The official docs on https://docs.litellm.ai/docs/proxy/docker_quick_start guide the users to setup postgres database by default through docker-compose.yml and for setting up pure config based setup, only the docker run command is given near the end I wanted to propose a new docker-compose.yml which is sufficient for setting up litellm to work directly from config file I have attached the files. Just wanted to know if i can open pull request to update the readme as well [docker-compose.yml](https://github.com/user-attachments/files/30502771/docker-compose.y…

_maintainer labels: bug, docs_

<https://github.com/BerriAI/litellm/issues/35084>

## #35527
**[Security]: Enabled drain endpoint accepts requests when no token is configured**

### Summary Enabling the graceful drain endpoint without configuring a drain token makes `/health/drain` callable by any network-reachable client. A successful call starts process-wide shutdown and takes the worker out of rotation ### Current behavior `health_drain()` intentionally does not use `user_api_key_auth` because Kubernetes `preStop` hooks commonly do not have proxy credentials `_authorize_drain_request()` returns immediately when neither `general_settings.drain_endpoint_token` nor `DRAIN_ENDPOINT_TOKEN` is set: ~~~python expected = _drain_endpoint_token() if expected is None: return ~~~ The endpoint is therefore protected only by `enable_drain_endpoint` ### Reproduction Enable the …

<https://github.com/BerriAI/litellm/issues/35527>

## #35532
**[Security]: JWT team_id_upsert creates arbitrary teams through a proxy-admin principal**

### Summary When JWT authentication has `team_id_upsert` enabled, a signed JWT containing a team ID that is absent from the database can cause the proxy to create that team during request authentication. The upsert calls the normal team-creation endpoint with a synthetic `PROXY_ADMIN` principal ### Current behavior `_get_team_db_check()` does the following when the team lookup returns no row: ~~~python new_team_data = NewTeamRequest(team_id=team_id) system_admin_user = UserAPIKeyAuth(user_role=LitellmUserRoles.PROXY_ADMIN) created_team_dict = await new_team( data=new_team_data, http_request=mock_request, user_api_key_dict=system_admin_user, ) ~~~ The normal `new_team()` endpoint then skips n…

<https://github.com/BerriAI/litellm/issues/35532>

## #35536
**[Security]: Responses ID security fails open for raw or ownerless response IDs**

### Summary The Responses ID security hook only checks ownership when an ID can be decrypted into an encrypted LiteLLM response ID with nonempty owner metadata. Raw IDs and IDs returned unchanged after encryption setup fails bypass the ownership check, and an encrypted ID with empty user and team fields is accepted for every non-admin key ### Current behavior The pre-call hook calls `check_user_access_to_response_id()` only when `_is_encrypted_response_id()` returns `True`. If decryption fails or the ID is not in the expected managed format, the hook forwards the ID without an ownership check When `LITELLM_SALT_KEY` and `master_key` are both absent, `_encrypt_response_id()` logs at debug lev…

<https://github.com/BerriAI/litellm/issues/35536>

## #35541
**[Bug]: Security vulnerabilities 1.94.0: CVE-2026-12772 CVE-2026-12795 CVE-2026-12796**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### What happened? [Snyk reports litellm](https://security.snyk.io/package/pip/litellm) 1.94.X/1.95.X/1.96.X/1.97.X all contain three known security vulnerabilities with publicly assigned CVEs. All three issues are direct dependencies and currently have no supported remediation path because no patched LiteLLM release is available. Affected vulnerabilities: CVE-2026-12772 – Insufficient Session Expiration (CWE-613), CVSS 7.1 CVE-2026-12795 – Missing Authentication for Critical Function (CWE-306), CVSS 6.9 CVE-2026-12796 – Insufficient Session Expiration (CWE-613), CVSS 5.3 CVE…

_maintainer labels: bug, SDK_

<https://github.com/BerriAI/litellm/issues/35541>

## #35648
**[Feature]: Add native DeepSeek V4 Flash Responses API support**

### Check for existing issues - [x] I have searched the existing issues and checked that this is not a duplicate. - Related: #27276 and #30722 / #30910 cover the Responses-to-Chat Completions bridge and DeepSeek tool filtering. This issue is specifically about calling DeepSeek's native Responses API, not translating Responses requests to Chat Completions. ### The Feature Please add first-class native Responses API support for the DeepSeek provider in LiteLLM, initially for `deepseek-v4-flash`. DeepSeek's official documentation now states that: - `deepseek-v4-flash` is currently the only DeepSeek model supported by the native Responses API; - the API uses the base URL `https://api.deepseek.co…

_maintainer labels: proxy, llm translation_

<https://github.com/BerriAI/litellm/issues/35648>

## #35682
**July Townhall Updates - 317 Bug Fixes, 95% E2E Testing**

https://docs.litellm.ai/blog/july-townhall-updates 38 Security Fixes, 317 Bug Fixes, and Autorouter V2

<https://github.com/BerriAI/litellm/issues/35682>

## #35765
**[Feature]: honor x-litellm-tags header on MCP gateway routes (tools/list, tools/call)**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### The Feature Parse the `x-litellm-tags` request header on MCP gateway requests (`/mcp` and `/{server_alias}/mcp`) and attach the tags to the spend logs of MCP operations (tools/call, tools/list), the same way LLM routes already do. Current behavior (verified in the v1.93.0 and v1.95.0 sources): - LLM routes parse the header in `LiteLLMProxyRequestSetup.add_litellm_data_to_request` (`litellm/proxy/litellm_pre_call_utils.py`, `if "x-litellm-tags" in headers:`), so tags land in `LiteLLM_SpendLogs.request_tags`. - On the MCP path nothing reads the header: `_experimental/mcp_se…

_maintainer labels: enhancement, proxy_

<https://github.com/BerriAI/litellm/issues/35765>

## #36342
**docs llms.txt has dead links, including the Docusaurus template intro page**

hey! i was testing an llms.txt validator against popular docs sites and docs.litellm.ai came back with 2 dead links out of 52: ``` $ curl -so /dev/null -w "%{http_code}\n" https://docs.litellm.ai/intro 404 $ curl -so /dev/null -w "%{http_code}\n" https://docs.litellm.ai/release_notes/archive 404 ``` the `/intro` one is worth a look beyond the 404: it's listed as "Docusaurus Setup Guide - Quickly learn to set up a Docusaurus site", which is the default Docusaurus template page leaking into the file. so whatever generates your llms.txt picked up a page that was later (rightly) deleted, and the entry stayed behind. `/release_notes/archive` looks like the same staleness, the page moved or got re…

<https://github.com/BerriAI/litellm/issues/36342>

## #36400
**openish**

openish

<https://github.com/BerriAI/litellm/issues/36400>

## #36646
**[Bug]: OpenAI passthrough `/v1/embeddings` writes no spend log row at all — billable tokens are unattributable, and budgets under-enforce**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. --- ### What happened? **In brief:** `POST /openai_passthrough/v1/embeddings` returns 200 and consumes real billable tokens, but LiteLLM writes **no `LiteLLM_SpendLogs` row at all** — not a zero-cost row, nothing. No `x-litellm-response-cost` header, and no movement in `LiteLLM_VerificationToken.spend`, so the spend is not booked off-ledger either. A virtual key with a hard budget can therefore spend without limit on this route. **What I expected to happen:** the call should write a spend row with `response_cost = prompt_tokens × input_cost_per_token` and move the calling key…

_maintainer labels: bug, proxy, llm translation_

<https://github.com/BerriAI/litellm/issues/36646>

## #36659
**[Bug]: OAUTH_TOKEN_INFO_ENDPOINT is under documented and doesn't exist for MSFT**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### What happened? As a customer / premium user, while trying to setup OAuth2 authentication on our proxy, I ran into errors with [OAUTH_TOKEN_INFO_ENDPOINT](https://github.com/BerriAI/litellm/blob/f64479e74d9d20d0edc806139b36d2a0db55a28c/litellm/proxy/auth/oauth2_check.py#L139) not being set. [Looking at the website](https://docs.litellm.ai/docs/proxy/oauth2), this requirement is barely documented, and the expected value is not specified. As we are using Microsoft Entra, I went looking for the endpoint, helped by the comment referencing the RFC (thanks!). Turns out [Microsof…

_maintainer labels: bug, proxy_

<https://github.com/BerriAI/litellm/issues/36659>

## #36743
**NA**



<https://github.com/BerriAI/litellm/issues/36743>

## #36898
**[Bug]: GET /health returns extra_headers and aws_session_token in plaintext**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. Related, not a duplicate: #18818 fixed masking of `extra_headers` on `/model/info`. `GET /health` is a different sanitizer. It still returns those values in full. `api_key` is stripped (CVE-2025-11203 class). `extra_headers` and `aws_session_token` were never added to that strip list. ### What happened? LiteLLM 1.96.2. No master key. A deployment in `config.yaml` has `extra_headers` (Azure `api-key`, Google `x-goog-api-key`, a Bearer token) and `aws_session_token`. `GET /health` returns those values in plaintext on the healthy (or unhealthy) row. `api_key` is absent. `api_bas…

_maintainer labels: proxy, llm translation_

<https://github.com/BerriAI/litellm/issues/36898>

## #36948
**[Feature]: Auto-detect context window (max_input_tokens) for LM Studio models from its native metadata API**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### The Feature For self-hosted/local providers that expose their own richer model-metadata API (LM Studio's `/api/v0/models` and `/api/v1/models`, both distinct from the OpenAI-compatible `/v1/models` LiteLLM currently calls for discovery), LiteLLM never queries or surfaces the provider's own `max_context_length` into a model's `model_info.max_input_tokens`. This affects every LM Studio model regardless of how it's added to LiteLLM — a manually written `model_list` entry, a model added via the Admin UI, or (once supported) a discovered wildcard model — because context window…

_maintainer labels: proxy, llm translation_

<https://github.com/BerriAI/litellm/issues/36948>

## #37143
**[Bug]: Docs mention litellm.turn_on_message_logging, which doesn't exist**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### What happened? It should probably be litellm.turn_off_message_logging at https://docs.litellm.ai/docs/proxy/logging#disable-message-redaction ### User Flow https://docs.litellm.ai/docs/proxy/logging#disable-message-redaction ### Proof the bug occurs https://docs.litellm.ai/docs/proxy/logging#disable-message-redaction ### What part of LiteLLM is this about? Docs ### What LiteLLM version are you on ? latest ### Twitter / LinkedIn details _No response_

_maintainer labels: bug, docs_

<https://github.com/BerriAI/litellm/issues/37143>

## #37459
**[Feature]: Native NeuralTrust TrustGuard guardrail**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate Searched open and closed issues for `neuraltrust`, `trustguard`, and `neural trust`. No existing issue ### The Feature Add NeuralTrust TrustGuard as a named LiteLLM guardrail, configurable from Guardrail Garden and from `config.yaml`, so a proxy admin can enforce TrustGuard policy on chat completions without a generic HTTP workaround TrustGuard already exposes `POST /v1/evaluate` ([Evaluate API](https://docs.neuraltrust.ai/trustguard/api/evaluate)). The missing piece is a first-class LiteLLM option that sends input and output, then applies `block` / `transform` / `report` / `a…

_maintainer labels: proxy_

<https://github.com/BerriAI/litellm/issues/37459>

## #37584
**Fix "novita/openai/gpt-oss-120b" entry in "model_prices_and_context_window.json"**

https://github.com/BerriAI/litellm/blob/007bd43cfb6eeeabe94d6aa77bd05dd3aa6aa1bf/model_prices_and_context_window.json#L45066-L45081 We also need to update [model_prices_and_context_window_backup.json](https://github.com/BerriAI/litellm/blob/007bd43cfb6eeeabe94d6aa77bd05dd3aa6aa1bf/litellm/model_prices_and_context_window_backup.json). supports_vision is factually false, but set to true

_maintainer labels: llm translation_

<https://github.com/BerriAI/litellm/issues/37584>

## #37761
**[Bug]: Perplexity Agent API models 400 on /v1/chat/completions unless the cost map happens to carry a reachable `mode: responses` entry**

### Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate. ### What happened? Perplexity's Agent API namespaces its model ids with a `perplexity/` prefix, so a litellm deployment for one reads `model: perplexity/perplexity/<id>`, the routing prefix plus the model's own name. Those deployments answer on `/v1/responses` but return 400 on `/v1/chat/completions`, with Perplexity rejecting a name nobody wrote, e.g. `Invalid model 'perplexity/nemotron-3-ultra-550b-a55b'` Whether an Agent API deployment works on chat completions comes down to whether the shipped cost map happens to carry a `mode: responses` entry that the model lookup actua…

_maintainer labels: bug, proxy, llm translation_

<https://github.com/BerriAI/litellm/issues/37761>

## #37890
**litellm**



<https://github.com/BerriAI/litellm/issues/37890>

## #38197
**MiniMax‑M2.7: message.content empty, usage all zero while reasoning_content has valid output, finish_reason=stop**

### Title: MiniMax‑M2.7: message.content empty, usage all zero while reasoning_content has valid output, finish_reason=stop **Environment** - LiteLLM version: xxx - Model: MiniMax‑M2.7 **Bug description** When calling MiniMax‑M2.7, upstream returns `finish_reason: stop` with valid text inside `reasoning_content / thinking_blocks`, but `message.content` is empty string. All usage token fields are zero. LiteLLM returns 200 OK to downstream client. Downstream application receives empty content and triggers massive client‑side retries. Root cause: 1. Minimax adapter does not map `reasoning_content` to top‑level `message.content` for M2.7 new response schema. 2. Token usage parsing path outdated …

<https://github.com/BerriAI/litellm/issues/38197>

## #38467
**[Feature]: Add Google-built OpenTelemetry Collector sidecars to GCP Terraform module**

## Check for existing issues - [x] I have searched the existing issues and checked that my issue is not a duplicate ## The Feature Add an opt-in Google-built OpenTelemetry Collector sidecar to the GCP Terraform module for the gateway and backend Cloud Run services The module already exposes `otel_endpoint`, `otel_exporter`, and related LiteLLM environment configuration. A Google Cloud operator can point those settings at `http://localhost:4318`, but the module does not create the local collector that Google recommends for Cloud Run. The remaining setup currently requires an out-of-band `gcloud run services replace` The opt-in deployment should provide a pinned, configurable Google-built coll…

<https://github.com/BerriAI/litellm/issues/38467>
