import { useEffect, useState } from "react";

import { getChunkDetail } from "../api";
import { Spinner } from "./ui";

/** A side panel that shows the clause behind a citation, and the full section around it. */
export default function CitationViewer({ citation, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");

  // Load the full section each time a different citation is clicked
  useEffect(() => {
    setDetail(null);
    setError("");

    async function loadDetail() {
      try {
        const data = await getChunkDetail(citation.chunk_id);
        setDetail(data);
      } catch (err) {
        setError(err.message);
      }
    }

    loadDetail();
  }, [citation.chunk_id]);

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Source [{citation.number}]</h2>
        <button onClick={onClose} className="text-gray-500 hover:text-gray-800">
          ✕
        </button>
      </div>

      <p className="text-sm font-medium">{citation.file_name}</p>
      <p className="mb-1 text-xs text-gray-500">{citation.section_path}</p>
      <p className="mb-3 text-xs text-gray-500">Page {citation.page_number}</p>

      {/* This is the exact text the answer was based on */}
      <div className="mb-4 whitespace-pre-wrap rounded border border-yellow-300 bg-yellow-50 p-3 text-sm">
        {citation.content}
      </div>

      <p className="mb-2 text-xs font-medium text-gray-500">Full section</p>
      {detail === null && error === "" && <Spinner />}
      {error !== "" && <p className="text-sm text-red-600">{error}</p>}
      {detail !== null && (
        <div className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded border p-3 text-xs text-gray-700">
          {detail.section_text}
        </div>
      )}
    </div>
  );
}