import { Badge } from "./ui";

// A short explanation under the status badge
const STATUS_HELP = {
  partial: "Only part of this answer could be confirmed from the contract.",
  conflicting: "The documents disagree and nothing shows which one applies. Check the sources.",
  not_found: "The contract does not seem to contain this.",
};

/** Show the answer text. Source numbers like [1] become clickable chips. */
function AnswerText({ content, citations, onCitationClick }) {
  // The split keeps the bracket parts, like "[1]" or "[2, 3]", as separate pieces
  const pieces = content.split(/(\[[\d,\s]+\])/);

  return (
    <p className="whitespace-pre-wrap text-sm leading-6">
      {pieces.map((piece, pieceIndex) => {
        const isBracket = /^\[[\d,\s]+\]$/.test(piece);
        if (!isBracket) {
          return <span key={pieceIndex}>{piece}</span>;
        }

        // A bracket can hold several numbers, like [2, 3]
        const numbers = piece.slice(1, -1).split(",");
        return (
          <span key={pieceIndex}>
            {numbers.map((numberText) => {
              const number = Number(numberText.trim());
              const citation = citations.find((item) => item.number === number);

              // If no source matches this number, show it as plain text
              if (citation === undefined) {
                return <span key={number}>[{number}]</span>;
              }
              return (
                <button
                  key={number}
                  onClick={() => onCitationClick(citation)}
                  className="mx-0.5 rounded bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-800 hover:bg-blue-200"
                >
                  [{number}]
                </button>
              );
            })}
          </span>
        );
      })}
    </p>
  );
}

/** One assistant answer with its status, a warning, clickable sources and a short notice. */
export default function AnswerCard({ message, onCitationClick }) {
  const statusHelp = STATUS_HELP[message.status];

  return (
    <div className="max-w-3xl rounded-lg bg-white p-4 shadow">
      <div className="mb-2 flex items-center gap-2">
        {message.status !== null && <Badge status={message.status} />}
        {statusHelp && <span className="text-xs text-gray-500">{statusHelp}</span>}
      </div>

      {/* The warning lists amendments, claims that could not be verified, and similar notes */}
      {message.warning && (
        <div className="mb-3 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          <span className="font-semibold">Please check. </span>
          {message.warning}
        </div>
      )}

      <AnswerText content={message.content} citations={message.citations} onCitationClick={onCitationClick} />

      {message.citations.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <p className="mb-2 text-xs font-medium text-gray-500">Sources</p>
          <ul className="space-y-1">
            {message.citations.map((citation) => (
              <li key={citation.number}>
                <button
                  onClick={() => onCitationClick(citation)}
                  className="text-left text-xs text-blue-700 hover:underline"
                >
                  [{citation.number}] {citation.file_name.split("/").pop()} · {citation.section_path} · page{" "}
                  {citation.page_number}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-3 text-xs text-gray-400">Decision support only. This is not legal advice.</p>
    </div>
  );
}