// ADAPTER — chat AI (Sprint E.1). Mode REAL (endpoint sudah ada sejak Sprint D).
import { pickAdapter } from './_adapter';
import * as real from './real/aiChat';

export const sendChatMessage = pickAdapter(
  'aiChat',
  real.sendChatMessage,
  real.sendChatMessage,
);

export { AI_CHAT_PATH, parseChatResponse } from './real/aiChat';
export type { AIChatResult } from '@/types/ai-chat';
