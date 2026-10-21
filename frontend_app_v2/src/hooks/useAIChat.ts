import { useCallback, useReducer } from 'react';
import { sendChatMessage } from '@/api/aiChat';
import { useApiClient } from '@/hooks/useApiClient';
import {
  buildChatRequest,
  chatErrorMessage,
  historyFromMessages,
} from '@/lib/ai-context';
import { generateUUID } from '@/lib/uuid';
import type {
  AIChatChannel,
  AIChatContext,
  AIChatUiMessage,
} from '@/types/ai-chat';

/**
 * useAIChat — state percakapan AI (dipakai `/ai/chat` & panel floating).
 *
 * Semua keputusan state ada di `chatReducer` (PURE) supaya bisa diuji tanpa DOM.
 * `sendMessage` tidak pernah throw: kegagalan menjadi pesan asisten + `error`.
 */

export interface AIChatState {
  messages: AIChatUiMessage[];
  loading: boolean;
  /** Kode error backend terakhir (`forbidden_context`, `not_implemented`, ...). */
  error: string | null;
  lastMessage: string | null;
  lastChannel: AIChatChannel;
}

export type AIChatAction =
  | { type: 'send_start'; message: AIChatUiMessage; channel: AIChatChannel }
  | { type: 'assistant'; message: AIChatUiMessage }
  | { type: 'error'; message: AIChatUiMessage; error: string }
  | { type: 'reset' };

export const INITIAL_AI_CHAT_STATE: AIChatState = {
  messages: [],
  loading: false,
  error: null,
  lastMessage: null,
  lastChannel: 'DESKTOP',
};

/** State awal dengan riwayat (mis. restore sesi / preview). */
export function createInitialChatState(
  messages: readonly AIChatUiMessage[] = [],
): AIChatState {
  return { ...INITIAL_AI_CHAT_STATE, messages: [...messages] };
}

export function chatReducer(state: AIChatState, action: AIChatAction): AIChatState {
  switch (action.type) {
    case 'send_start':
      return {
        messages: [...state.messages, action.message],
        loading: true,
        error: null,
        lastMessage: action.message.content,
        lastChannel: action.channel,
      };
    case 'assistant':
      return {
        ...state,
        messages: [...state.messages, action.message],
        loading: false,
        error: null,
      };
    case 'error':
      return {
        ...state,
        messages: [...state.messages, action.message],
        loading: false,
        error: action.error,
      };
    case 'reset':
      return INITIAL_AI_CHAT_STATE;
    default:
      return state;
  }
}

function assistantMessage(
  content: string,
  response?: AIChatUiMessage['response'],
  error?: string,
): AIChatUiMessage {
  return {
    id: generateUUID(),
    role: 'assistant',
    content,
    ...(response === undefined ? {} : { response }),
    ...(error === undefined ? {} : { error }),
  };
}

export interface UseAIChatResult {
  messages: AIChatUiMessage[];
  loading: boolean;
  error: string | null;
  lastMessage: string | null;
  sendMessage: (
    text: string,
    context: AIChatContext | null,
    channel: AIChatChannel,
  ) => Promise<void>;
  retryWithoutContext: (context: AIChatContext) => Promise<void>;
  reset: () => void;
}

export function useAIChat(options: { initialMessages?: AIChatUiMessage[] } = {}): UseAIChatResult {
  const apiClient = useApiClient();
  const [state, dispatch] = useReducer(
    chatReducer,
    options.initialMessages ?? [],
    createInitialChatState,
  );

  const sendMessage = useCallback(
    async (text: string, context: AIChatContext | null, channel: AIChatChannel) => {
      const message = text.trim();
      if (message.length === 0 || state.loading) return;

      const history = historyFromMessages(state.messages);
      dispatch({
        type: 'send_start',
        message: { id: generateUUID(), role: 'user', content: message },
        channel,
      });

      try {
        const result = await sendChatMessage(
          apiClient,
          buildChatRequest(message, history, context, channel),
        );

        if (result.ok) {
          dispatch({
            type: 'assistant',
            message: assistantMessage(result.answer, result),
          });
        } else {
          dispatch({
            type: 'error',
            message: assistantMessage(chatErrorMessage(result.error), undefined, result.error),
            error: result.error,
          });
        }
      } catch {
        dispatch({
          type: 'error',
          message: assistantMessage(chatErrorMessage('network_error'), undefined, 'network_error'),
          error: 'network_error',
        });
      }
    },
    [apiClient, state.loading, state.messages],
  );

  const retryWithoutContext = useCallback(
    async (context: AIChatContext) => {
      if (state.lastMessage === null) return;
      await sendMessage(state.lastMessage, context, state.lastChannel);
    },
    [sendMessage, state.lastChannel, state.lastMessage],
  );

  const reset = useCallback(() => dispatch({ type: 'reset' }), []);

  return {
    messages: state.messages,
    loading: state.loading,
    error: state.error,
    lastMessage: state.lastMessage,
    sendMessage,
    retryWithoutContext,
    reset,
  };
}
