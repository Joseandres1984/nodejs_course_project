# LUMEN Conversational UI v2

The conversational dashboard now:

- shows current phase, bottleneck, next action and bounded autonomy;
- surfaces the latest learning hypothesis, exploration rate and confidence;
- shows a visible processing state instead of appearing frozen;
- aborts a browser wait after 14 seconds;
- relies on the A2A conversational backend, which itself falls back to a deterministic grounded answer after a short Workers AI timeout;
- preserves human gates for financial and binding actions.
