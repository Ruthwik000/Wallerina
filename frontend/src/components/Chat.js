"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat } from "@/lib/api";
import { useWallet } from "./WalletProvider";
import styles from "./Chat.module.css";

const SUGGESTIONS = [
  "How risky is my portfolio right now?",
  "Which asset contributes the most risk, and why?",
  "What would happen if I moved half of it into stablecoins?",
  "What does my 5th percentile outcome actually mean?",
  "Why is one of my tokens classified as unknown?",
];

let nextId = 0;
const createId = () => `m${nextId++}`;

export default function Chat({ variant = "page" }) {
  const { address, connected } = useWallet();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [toolNotice, setToolNotice] = useState(null);

  const abortRef = useRef(null);
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);

  // Keep the newest message in view as text streams in.
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, toolNotice]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // A different wallet is a different conversation.
  useEffect(() => {
    abortRef.current?.abort();
    setMessages([]);
    setStreaming(false);
    setToolNotice(null);
  }, [address]);

  const send = useCallback(
    async (text) => {
      const question = text.trim();
      if (!question || streaming || !connected) return;

      const controller = new AbortController();
      abortRef.current = controller;

      // History excludes the message being sent; the backend appends it.
      const history = messages
        .filter((message) => !message.failed)
        .map(({ role, content }) => ({ role, content }));

      const replyId = createId();

      setMessages((current) => [
        ...current,
        { id: createId(), role: "user", content: question },
        { id: replyId, role: "assistant", content: "" },
      ]);
      setInput("");
      setStreaming(true);
      setToolNotice(null);

      const appendToReply = (chunk) =>
        setMessages((current) =>
          current.map((message) =>
            message.id === replyId
              ? { ...message, content: message.content + chunk }
              : message
          )
        );

      try {
        await streamChat({
          walletAddress: address,
          message: question,
          history,
          signal: controller.signal,
          onEvent: (event) => {
            if (event.type === "text") {
              appendToReply(event.text);
            } else if (event.type === "tool") {
              setToolNotice("Running a simulation");
            } else if (event.type === "error") {
              setMessages((current) =>
                current.map((message) =>
                  message.id === replyId
                    ? { ...message, content: event.message, failed: true }
                    : message
                )
              );
            } else if (event.type === "done") {
              setToolNotice(null);
            }
          },
        });
      } catch (error) {
        if (error.name === "AbortError") return;
        setMessages((current) =>
          current.map((message) =>
            message.id === replyId
              ? { ...message, content: error.message, failed: true }
              : message
          )
        );
      } finally {
        setStreaming(false);
        setToolNotice(null);
      }
    },
    [address, connected, messages, streaming]
  );

  const onKeyDown = (event) => {
    // Enter sends; Shift+Enter inserts a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send(input);
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
    setToolNotice(null);
  };

  return (
    <div className={`${styles.chat} ${variant === "panel" ? styles.panelVariant : ""}`}>
      <div className={styles.scroll} ref={scrollRef}>
        {messages.length === 0 ? (
          <div className={styles.intro}>
            <p className={styles.introTitle}>Ask about this wallet</p>
            <p className={styles.introText}>
              Questions are answered from the figures the risk engine has
              already computed for your holdings. Ask what a number means, where
              your risk is concentrated, or what a different allocation would
              look like.
            </p>
            <ul className={styles.suggestions}>
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  <button
                    type="button"
                    className={styles.suggestion}
                    onClick={() => send(suggestion)}
                    disabled={!connected}
                  >
                    {suggestion}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <ul className={styles.messages}>
            {messages.map((message) => (
              <li
                key={message.id}
                className={`${styles.message} ${styles[message.role]} ${
                  message.failed ? styles.failed : ""
                }`}
              >
                <span className={styles.role}>
                  {message.role === "user" ? "You" : "Wallerina"}
                </span>
                <div className={styles.content}>
                  {message.content || (
                    <span className={styles.caret} aria-label="Thinking" />
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}

        {toolNotice && (
          <p className={styles.toolNotice} role="status">
            {toolNotice}
          </p>
        )}
      </div>

      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
      >
        <textarea
          ref={textareaRef}
          className={styles.input}
          rows={variant === "panel" ? 2 : 3}
          placeholder={
            connected ? "Ask a question about this wallet" : "Connect a wallet first"
          }
          value={input}
          disabled={!connected || streaming}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
          aria-label="Message"
        />
        <div className={styles.actions}>
          <span className={styles.hint}>
            {streaming ? "Writing…" : "Enter to send · Shift+Enter for a new line"}
          </span>
          {streaming ? (
            <button type="button" className={styles.stop} onClick={stop}>
              Stop
            </button>
          ) : (
            <button
              type="submit"
              className={styles.send}
              disabled={!connected || !input.trim()}
            >
              Send
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
