import { useState } from "react";

import { Button } from "./ui";

/** A text box and a send button. Enter sends, Shift+Enter adds a new line. */
export default function MessageInput({ onSend, disabled, focusVendor, onClearFocus }) {
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
    <div>
      {/* Follow-up questions search this contract. The user can stop that with the x. */}
      {focusVendor !== "" && (
        <div className="mb-2 flex items-center gap-2 text-xs">
          <span className="text-gray-500">Follow-up questions are about:</span>
          <span className="flex items-center gap-1 rounded-full bg-blue-100 px-2 py-1 font-medium text-blue-800">
            {focusVendor}
            <button onClick={onClearFocus} title="Search all contracts again" className="hover:text-blue-950">
              ✕
            </button>
          </span>
        </div>
      )}

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
    </div>
  );
}