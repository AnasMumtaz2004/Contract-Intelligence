import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { clearToken, deleteDocument, getDocuments } from "../api";
import UploadDialog from "../components/UploadDialog";
import { Badge, Button } from "../components/ui";

/** The main page: a list of all uploaded documents with their status. */
export default function Library() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState([]);
  const [error, setError] = useState("");
  const [showUpload, setShowUpload] = useState(false);

  /** Load the document list from the backend. */
  async function loadDocuments() {
    try {
      const data = await getDocuments();
      setDocuments(data);
    } catch (err) {
      setError(err.message);
    }
  }

  // Load the list once when the page opens
  useEffect(() => {
    loadDocuments();
  }, []);

  // While any document is still processing, reload the list every 3 seconds
  useEffect(() => {
    const hasActiveDocument = documents.some(
      (document) => document.status !== "ready" && document.status !== "failed"
    );
    if (!hasActiveDocument) {
      return;
    }

    const timer = setInterval(loadDocuments, 3000);
    return () => clearInterval(timer);
  }, [documents]);

  /** Close the upload popup and refresh the list. */
  function handleCloseUpload() {
    setShowUpload(false);
    loadDocuments();
  }

  /** Ask for confirmation, then delete one document. */
  async function handleDelete(document) {
    const confirmed = window.confirm("Delete " + document.file_name + "?");
    if (!confirmed) {
      return;
    }
    await deleteDocument(document.id);
    loadDocuments();
  }

  /** Log out and go to the login page. */
  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  return (
    <div className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Contract Library</h1>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => navigate("/chat")}>
            Ask questions
          </Button>
          <Button onClick={() => setShowUpload(true)}>Upload contract</Button>
          <Button variant="secondary" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>

      {error !== "" && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {documents.length === 0 ? (
        <p className="rounded bg-white p-8 text-center text-gray-500 shadow">
          No contracts yet. Click "Upload contract" to add your first one.
        </p>
      ) : (
        <div className="overflow-x-auto rounded bg-white shadow">
          <table className="w-full text-left text-sm">
            <thead className="border-b bg-gray-50 text-gray-600">
              <tr>
                <th className="p-3">File</th>
                <th className="p-3">Vendor</th>
                <th className="p-3">Type</th>
                <th className="p-3">Status</th>
                <th className="p-3">Pages</th>
                <th className="p-3">Chunks</th>
                <th className="p-3">Uploaded</th>
                <th className="p-3"></th>
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id} className="border-b last:border-b-0">
                  <td className="p-3">{document.file_name}</td>
                  <td className="p-3">{document.vendor_name}</td>
                  <td className="p-3">{document.document_type}</td>
                  <td className="p-3">
                    <Badge status={document.status} />
                    {document.status === "failed" && (
                      <p className="mt-1 max-w-xs text-xs text-red-600">{document.error_message}</p>
                    )}
                  </td>
                  <td className="p-3">{document.page_count}</td>
                  <td className="p-3">{document.chunk_count}</td>
                  <td className="p-3">{new Date(document.created_at).toLocaleString()}</td>
                  <td className="p-3">
                    <Button variant="danger" onClick={() => handleDelete(document)}>
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showUpload && <UploadDialog onClose={handleCloseUpload} />}
    </div>
  );
}