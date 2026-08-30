# OpenAI capability check for Ted V1

Verified against official OpenAI documentation on 30 August 2026.

## Decision

| Ted input | OpenAI path | Model | Status |
| --- | --- | --- | --- |
| Typed messages | Responses API text input | `gpt-5.6-terra` | Supported |
| Meal photos | Responses API image input | `gpt-5.6-terra` | Supported |
| Voice notes | Audio Transcriptions API | `gpt-transcribe` | Supported |
| Health-plan PDFs | Responses API file input | `gpt-5.6-terra` | Supported |

`gpt-5.6-terra` is the balanced model in the current GPT-5.6 family. Ted needs more than basic classification: it must understand mixed-language messages, inspect meal photos, read health plans and produce dependable structured data. We will validate its quality with fixed examples before considering the cheaper Luna model.

`gpt-transcribe` is designed for completed audio files and supports multilingual audio, language hints, keyword hints and code-switching. That matches downloaded WhatsApp voice notes better than a live Realtime session.

## Important implementation details

- Use the Responses API for text, images and PDFs.
- Ask for structured output when turning an input into food, nutrition, plan or progress fields.
- Send meal photos as image inputs. Do not use an image-generation model; Ted needs image understanding, not image creation.
- Download each WhatsApp voice note, transcribe it with `gpt-transcribe`, show uncertain wording to the user when needed, then pass the transcript through the same interpretation route as typed text.
- Send health-plan PDFs as `input_file`. The API extracts both PDF text and page images on vision-capable models.
- Start PDF processing with `detail: "auto"`. Raise it to `high` only when small print, charts or diagrams require it because higher detail uses more input tokens.
- Keep raw WhatsApp media in Ted's own storage as required by the product scope. OpenAI processing is not Ted's long-term media store.

## What is and is not verified

Official documentation verifies that all four required input types are currently supported. A real API request has not been run because no `OPENAI_API_KEY` is configured in this project yet. Model access, account limits, real costs and output quality therefore remain unverified until live test fixtures are run.

## Official sources

- [OpenAI model catalog](https://developers.openai.com/api/docs/models)
- [GPT-5.6 Terra model details](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [GPT-Transcribe model details](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [OpenAI file inputs](https://developers.openai.com/api/docs/guides/file-inputs)
- [OpenAI audio and speech](https://developers.openai.com/api/docs/guides/audio)
