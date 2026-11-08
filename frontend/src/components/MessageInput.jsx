import { useState } from "react";

import { Button } from "./ui";

/** A text box and a send button. Enter sends, Shift+Enter adds a new line. */
export default function MessageInput({ onSend, disabled }) {
  const [text, setText] = useState("");

  /** Send the question and clear the box. */
  function handleSend() {
    const question = text.trim();
    if (question === "" || disabled) {
      return;
    }
    onSend(question);
    setText("");
  }

  /** Send when Enter is pressed without Shift. */
  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex items-end gap-3">
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={2}
        placeholder="Ask a question about your contracts..."
        className="flex-1 resize-none rounded border border-gray-300 px-3 py-2 text-sm"
      />
      <Button onClick={handleSend} disabled={disabled || text.trim() === ""}>
        Send
      </Button>
    </div>
  );
}