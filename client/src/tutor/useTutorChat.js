import { useCallback, useEffect, useRef, useState } from 'react';

import { API_BASE_URL, api, toFormError } from '../lib/api.js';

const parseEventBlock = (block) => {
  let event = 'message';
  let id = '';
  const data = [];
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('id:')) id = line.slice(3).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  return { event, id, data: JSON.parse(data.join('\n') || '{}') };
};

/**
 * `sourceId` is the material the thread is about, or null for the whole kit.
 * It is part of the conversation the server hands back, so switching files
 * loads that file's history rather than one shared thread.
 */
export const useTutorChat = (kitId, language, sourceId = null, { enabled = true } = {}) => {
  const [messages, setMessages] = useState([]);
  const [quota, setQuota] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [error, setError] = useState(null);
  const abortRef = useRef(null);
  const streamingSessionRef = useRef(null);

  const load = useCallback(async () => {
    if (!enabled || !kitId) return;
    try {
      const { data } = await api.get(`/chat/conversation/${kitId}`, {
        params: { language, sourceId: sourceId || undefined },
      });
      setMessages(data.messages);
      setQuota(data.quota);
      setError(null);
    } catch (err) { setError(toFormError(err)); }
  }, [enabled, kitId, language, sourceId]);

  useEffect(() => { load(); return () => abortRef.current?.abort(); }, [load]);

  const updateAssistant = useCallback((id, patcher) => {
    setMessages((current) => current.map((message) => message.id === id ? patcher(message) : message));
  }, []);

  const stream = useCallback(async (sessionId) => {
    if (streamingSessionRef.current === sessionId) return;
    streamingSessionRef.current = sessionId;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    let lastEventId = '';
    let terminal = false;

    try {
      for (let attempt = 0; attempt < 4 && !terminal; attempt += 1) {
        try {
        const response = await fetch(`${API_BASE_URL}/chat/${sessionId}/stream`, {
          credentials: 'include',
          headers: { Accept: 'text/event-stream', ...(lastEventId && { 'Last-Event-ID': lastEventId }) },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`Stream request failed (${response.status})`);
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n');
          let boundary;
          while ((boundary = buffer.indexOf('\n\n')) >= 0) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            if (!block.trim() || block.startsWith(':')) continue;
            const frame = parseEventBlock(block);
            lastEventId = frame.id || lastEventId;
            if (frame.event === 'delta') {
              updateAssistant(sessionId, (message) => ({ ...message, content: message.content + frame.data.text, status: 'streaming' }));
            } else if (frame.event === 'done') {
              terminal = true;
              updateAssistant(sessionId, (message) => ({ ...message, citations: frame.data.citations, status: 'complete' }));
              setSuggestions(frame.data.suggestedFollowups ?? []);
              setQuota(frame.data.quota);
              setError(null);
            } else if (frame.event === 'error') {
              terminal = true;
              updateAssistant(sessionId, (message) => ({ ...message, status: 'failed', error: frame.data }));
              setError(frame.data);
            }
          }
          if (done) break;
        }
        if (!terminal) throw new Error('Stream ended before its terminal event');
        } catch (err) {
          if (controller.signal.aborted) return;
          if (attempt === 3) {
            updateAssistant(sessionId, (message) => ({ ...message, status: 'failed', error: { message: err.message, retryable: true } }));
            setError({ code: 'connection_lost', message: err.message, retryable: true });
            return;
          }
          await new Promise((resolve) => window.setTimeout(resolve, 300 * 2 ** attempt));
        }
      }
    } finally {
      if (streamingSessionRef.current === sessionId) streamingSessionRef.current = null;
    }
  }, [updateAssistant]);

  useEffect(() => {
    if (!enabled) return undefined;
    const unfinished = messages.find((message) => message.role === 'assistant' && (message.status === 'queued' || message.status === 'streaming'));
    if (unfinished) void stream(unfinished.id);
    return undefined;
  }, [enabled, messages, stream]);

  const send = useCallback(async (content) => {
    const text = content.trim();
    if (!enabled || !kitId || !text) return;
    try {
      const { data } = await api.post('/chat', { kitId, sourceId: sourceId || undefined, content: text, language });
      setMessages((current) => [...current, data.userMessage, data.assistantMessage]);
      setQuota(data.quota);
      setError(null);
      await stream(data.sessionId);
    } catch (err) { setError(toFormError(err)); }
  }, [enabled, kitId, sourceId, language, stream]);

  const retry = useCallback(async (failedSessionId) => {
    try {
      const { data } = await api.post(`/chat/${failedSessionId}/retry`);
      setMessages((current) => [...current, data.assistantMessage]);
      setError(null);
      await stream(data.sessionId);
    } catch (err) { setError(toFormError(err)); }
  }, [stream]);

  return { messages, quota, suggestions, error, send, retry };
};
