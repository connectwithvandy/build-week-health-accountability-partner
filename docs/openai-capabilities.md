# AI capability check for Ted V1

Last checked against official OpenAI documentation on 2 September 2026.

## Decision

| Ted input | Path | Model | Status |
| --- | --- | --- | --- |
| Typed messages | Hermes through OpenRouter | Sonnet 5 primary; `openai/gpt-5.3-codex` fallback | Both models passed separate direct calls |
| Meal photos | Hermes through OpenRouter | Sonnet 5 primary; `openai/gpt-5.3-codex` fallback | Both models support image input; Ted flow not yet verified |
| Voice notes | Separate speech transcription | `gpt-transcribe` | Required because Codex does not accept audio |
| Health-plan PDFs | File extraction, then Hermes through OpenRouter | Sonnet 5 primary; `openai/gpt-5.3-codex` fallback | Ted flow not yet verified |

Ted's live conversational route is `anthropic/claude-sonnet-5` first and `openai/gpt-5.3-codex` as its automatic fallback, both through OpenRouter. Each model passed a separate direct non-WhatsApp request on 2 September 2026. A forced fallback and the complete WhatsApp flow still need tests.

`gpt-transcribe` is designed for completed audio files and supports multilingual audio, language hints, keyword hints and code-switching. That matches downloaded WhatsApp voice notes better than a live Realtime session.

## Important implementation details

- Send conversational text and supported image inputs through OpenRouter to Sonnet 5, with `openai/gpt-5.3-codex` available when the primary fails.
- Ask for structured output when turning an input into food, nutrition, plan or progress fields.
- Send meal photos as image inputs. Do not use an image-generation model; Ted needs image understanding, not image creation.
- Download each WhatsApp voice note, transcribe it with `gpt-transcribe`, show uncertain wording to the user when needed, then send the transcript through the same OpenRouter path as typed text.
- Extract text and page images from health-plan PDFs before sending the useful content through the conversational path. The complete Hermes flow must be tested before this is promised to beta users.
- Start PDF processing with `detail: "auto"`. Raise it to `high` only when small print, charts or diagrams require it because higher detail uses more input tokens.
- Keep raw WhatsApp media in Ted's own storage as required by the product scope. OpenAI processing is not Ted's long-term media store.

## What is and is not verified

Both OpenRouter model paths passed separate direct Hermes calls. The automatic cutover itself, WhatsApp delivery, meal-photo interpretation, PDF processing, voice transcription, real costs and output quality remain unverified after this routing change.

## OpenRouter list-price check

Checked on 2 September 2026, per 1 million tokens:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| Sonnet 5 | $2.00 | $0.20 | $10.00 |
| GPT-5.3-Codex | $1.75 | $0.175 | $14.00 |

These are public list prices, not Vandy's account-specific spend. The signed-in OpenRouter dashboard was not available in this session.

## Official sources

- [GPT-5.3 Codex model details](https://developers.openai.com/api/docs/models/gpt-5.3-codex)
- [OpenAI latest-model guidance](https://developers.openai.com/api/docs/guides/latest-model)
- [GPT-Transcribe model details](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [OpenAI file inputs](https://developers.openai.com/api/docs/guides/file-inputs)
- [OpenAI audio and speech](https://developers.openai.com/api/docs/guides/audio)
- [OpenRouter Sonnet 5 pricing](https://openrouter.ai/anthropic/claude-sonnet-5)
- [OpenRouter GPT-5.3-Codex pricing](https://openrouter.ai/openai/gpt-5.3-codex)
