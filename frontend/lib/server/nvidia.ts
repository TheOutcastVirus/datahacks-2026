import axios from 'axios';

const NVIDIA_NIM_URL = 'https://integrate.api.nvidia.com/v1/chat/completions';
const MODEL = 'moonshotai/kimi-k2.5';

type NIMDeltaPart =
  | string
  | {
      text?: string;
      type?: string;
    };

type NIMChoice = {
  message?: {
    content?: string | NIMDeltaPart[];
    reasoning_content?: string | NIMDeltaPart[];
  };
};

function extractTextParts(content: string | NIMDeltaPart[] | undefined) {
  if (!content) {
    return '';
  }

  if (typeof content === 'string') {
    return content;
  }

  return content
    .map((part) => (typeof part === 'string' ? part : part.text ?? ''))
    .join('');
}

function getChoiceText(choice: NIMChoice | undefined) {
  return (
    extractTextParts(choice?.message?.content) ||
    extractTextParts(choice?.message?.reasoning_content)
  );
}

export type NvidiaPromptOptions = {
  maxTokens?: number;
  temperature?: number;
  topP?: number;
  timeoutMs?: number;
};

export async function runNvidiaPrompt(
  systemPrompt: string,
  userPrompt: string,
  options?: NvidiaPromptOptions,
) {
  const apiKey = process.env.NVIDIA_API_KEY;
  if (!apiKey) {
    throw new Error('Missing NVIDIA_API_KEY.');
  }

  const maxTokens = options?.maxTokens ?? 4096;
  const temperature = options?.temperature ?? 0.2;
  const topP = options?.topP ?? 0.9;
  const timeoutMs = options?.timeoutMs ?? 30_000;

  const response = await axios.post(
    NVIDIA_NIM_URL,
    {
      model: MODEL,
      messages: [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      max_tokens: maxTokens,
      temperature,
      top_p: topP,
      stream: false,
      // Kimi accepts `thinking`; keep it off for latency-sensitive paths.
      chat_template_kwargs: { thinking: false },
    },
    {
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      timeout: timeoutMs,
    },
  );

  const text = getChoiceText(response.data?.choices?.[0]);
  if (!text.trim()) {
    throw new Error('NVIDIA NIM returned an empty response.');
  }

  return text.trim();
}

export function extractJsonObject(input: string) {
  const firstBrace = input.indexOf('{');
  const lastBrace = input.lastIndexOf('}');

  if (firstBrace === -1 || lastBrace === -1 || lastBrace <= firstBrace) {
    throw new Error('Model response did not contain a JSON object.');
  }

  return input.slice(firstBrace, lastBrace + 1);
}
