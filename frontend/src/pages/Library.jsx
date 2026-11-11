import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { clearToken, deleteDocument, getDocuments, releaseDocument } from "../api";
import MetadataForm from "../components/MetadataForm";
import UploadDialog from "../components/UploadDialog";
import { Badge, Button, EmptyState, ErrorBanner, Modal, PageLoading, useToast } from "../components/ui";

// Documents without a vendor are stored under this name
const UNASSIGNED_VENDOR = "Unassigned";

// After these statuses nothing changes by itself, so the page stops asking for updates
const FINAL_STATUSES = ["ready", "failed", "quarantined"];

/** Sort by effective date, oldest first. Documents without a date come first. */
function compareByDate(first, second) {
  const firstDate = first.effective_date ?? "";
  const secondDate = second.effective_date ?? "";

  if (firstDate < secondDate) {
    return -1;
  }
  if (firstDate > secondDate) {
    return 1;
  }
  return first.id - second.id;
}

/** Put the documents of one vendor in order: each main contract, then its amendments under it. */
function orderFamily(items) {
  const idsInFamily = {};
  for (const item of items) {
    idsInFamily[item.id] = true;
  }

  const roots = [];
  const children = [];
  for (const item of items) {
    const hasParentHere = item.parent_document_id !== null && idsInFamily[item.parent_document_id] === true;
    if (hasParentHere) {
      children.push(item);
    } else {
      roots.push(item);
    }
  }
  roots.sort(compareByDate);

  const rows = [];
  for (const root of roots) {
    rows.push({ item: root, depth: 0 });

    const kids = [];
    for (const child of children) {
      if (child.parent_document_id === root.id) {
        kids.push(child);
      }
    }
    kids.sort(compareByDate);
    for (const kid of kids) {
      rows.push({ item: kid, depth: 1 });
    }
  }
  return rows;
}

/** Group the documents by vendor. Documents without a vendor come first, so they get noticed. */
function groupByVendor(documents) {
  const groups = {};
  for (const item of documents) {
    if (!(item.vendor_name in groups)) {
      groups[item.vendor_name] = [];
    }
    groups[item.vendor_name].push(item);
  }

  const vendorNames = Object.keys(groups).sort();
  if (vendorNames.includes(UNASSIGNED_VENDOR)) {
    const others = [];
    for (const name of vendorNames) {
      if (name !== UNASSIGNED_VENDOR) {
        others.push(name);
      }
    }
    vendorNames.length = 0;
    vendorNames.push(UNASSIGNED_VENDOR, ...others);
  }

  const result = [];
  for (const vendorName of vendorNames) {
    result.push({ vendorName: vendorName, rows: orderFamily(groups[vendorName]) });
  }
  return result;
}

/** Describe how a document was read, like "OCR" or "text". */
function describeParser(parserUsed) {
  const labels = [];
  if (parserUsed.includes("ocr")) {
    labels.push("OCR");
  }
  if (parserUsed.includes("tables")) {
    labels.push("tables");
  }
  if (labels.length === 0) {
    return "text";
  }
  return labels.join(" + ");
}

/** The main page: all uploaded documents, grouped by contract, with their status. */
export default function Library() {
  const navigate = useNavigate();
  const showToast = useToast();
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const [editingDocument, setEditingDocument] = useState(null);

  /** Load the document list from the backend. */
  async function loadDocuments() {
    try {
      const data = await getDocuments();
      setDocuments(data);
      setError("");
    } catch (err) {
      setError(err.message);
    }
    setIsLoading(false);
  }

  // Load the list once when the page opens
  useEffect(() => {
    loadDocuments();
  }, []);

  // While any document is still processing, reload the list every 3 seconds
  useEffect(() => {
    const hasActiveDocument = documents.some((item) => !FINAL_STATUSES.includes(item.status));
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

  /** Close the edit popup and refresh the list. */
  function handleCloseEdit() {
    setEditingDocument(null);
    loadDocuments();
  }

  /** Ask for confirmation, then delete one document. */
  async function handleDelete(item) {
    const confirmed = window.confirm("Delete " + item.file_name + "?");
    if (!confirmed) {
      return;
    }

    try {
      await deleteDocument(item.id);
      showToast("Document deleted", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
    loadDocuments();
  }

  /** Let a blocked document through, after the user confirmed that the sender is trusted. */
  async function handleRelease(item) {
    const confirmed = window.confirm(
      "Release " +
        item.file_name +
        " only if you trust the sender. Its instruction-like sentences will still be removed from the text."
    );
    if (!confirmed) {
      return;
    }

    try {
      await releaseDocument(item.id);
      showToast("Released. The document is being processed.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
    loadDocuments();
  }

  /** Log out and go to the login page. */
  function handleLogout() {
    clearToken();
    navigate("/login");
  }

  const groups = groupByVendor(documents);

  return (
    <div className="mx-auto max-w-6xl p-4 md:p-6">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Contract Library</h1>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" onClick={() => navigate("/chat")}>
            Ask questions
          </Button>
          <Button onClick={() => setShowUpload(true)}>Upload contract</Button>
          <Button variant="secondary" onClick={handleLogout}>
            Log out
          </Button>
        </div>
      </div>

      <ErrorBanner message={error} onRetry={loadDocuments} />

      {isLoading && <PageLoading text="Loading your contracts..." />}

      {!isLoading && error === "" && documents.length === 0 && (
        <EmptyState title="No contracts yet" text="Upload a PDF to get started. The first one takes a minute, because the models load.">
          <Button onClick={() => setShowUpload(true)}>Upload contract</Button>
        </EmptyState>
      )}

      <div className="space-y-6">
        {groups.map((group) => (
          <section key={group.vendorName} className="rounded bg-white shadow">
            <div className="border-b px-4 py-3">
              <h2 className="font-semibold">{group.vendorName}</h2>
              {group.vendorName === UNASSIGNED_VENDOR ? (
                <p className="text-xs text-amber-700">These documents have no vendor yet. Click Edit to set one.</p>
              ) : (
                <p className="text-xs text-gray-500">{group.rows.length} document(s)</p>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <thead className="border-b bg-gray-50 text-gray-600">
                  <tr>
                    <th className="p-3">File</th>
                    <th className="p-3">Type</th>
                    <th className="p-3">Effective</th>
                    <th className="p-3">Status</th>
                    <th className="p-3">Pages</th>
                    <th className="p-3">Chunks</th>
                    <th className="p-3">Read with</th>
                    <th className="p-3"></th>
                  </tr>
                </thead>
                <tbody>
                  {group.rows.map((row) => (
                    <tr key={row.item.id} className="border-b last:border-b-0">
                      <td className="p-3">
                        {/* Amendments are shown under the contract they belong to */}
                        {row.depth > 0 && <span className="mr-1 text-gray-400">↳</span>}
                        <span className={row.depth > 0 ? "ml-4" : ""}>{row.item.file_name.split("/").pop()}</span>
                      </td>
                      <td className="p-3">{row.item.document_type}</td>
                      <td className="p-3">{row.item.effective_date ?? "-"}</td>
                      <td className="p-3">
                        <Badge status={row.item.status} />
                        {/* The reason is shown for documents that failed or were blocked by the scan */}
                        {(row.item.status === "failed" || row.item.status === "quarantined") && (
                          <p
                            className={
                              "mt-1 max-w-sm text-xs " +
                              (row.item.status === "quarantined" ? "text-orange-700" : "text-red-600")
                            }
                          >
                            {row.item.error_message}
                          </p>
                        )}
                      </td>
                      <td className="p-3">{row.item.page_count}</td>
                      <td className="p-3">{row.item.chunk_count}</td>
                      <td className="p-3">{describeParser(row.item.parser_used)}</td>
                      <td className="p-3">
                        <div className="flex gap-2">
                          {row.item.status === "quarantined" && (
                            <Button variant="danger" onClick={() => handleRelease(row.item)}>
                              Release
                            </Button>
                          )}
                          {row.item.status === "ready" && (
                            <Button variant="secondary" onClick={() => setEditingDocument(row.item)}>
                              Edit
                            </Button>
                          )}
                          <Button variant="danger" onClick={() => handleDelete(row.item)}>
                            Delete
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        ))}
      </div>

      {showUpload && <UploadDialog onClose={handleCloseUpload} />}

      {editingDocument !== null && (
        <Modal title="Edit details" onClose={handleCloseEdit}>
          <p className="mb-4 text-sm text-gray-600">{editingDocument.file_name.split("/").pop()}</p>
          <MetadataForm
            key={editingDocument.id}
            documentItem={editingDocument}
            useSuggestions={false}
            onDone={handleCloseEdit}
          />
        </Modal>
      )}
    </div>
  );
}