import { useEffect, useState } from "react";

import { getDocument, releaseDocument, uploadDocument } from "../api";
import MetadataForm from "./MetadataForm";
import { Button, Modal, Spinner } from "./ui";

const DOCUMENT_TYPES = ["Other", "MSA", "NDA", "SOW", "Amendment", "Exhibit"];

// The steps a document goes through, in order
const STEPS = ["uploaded", "parsing", "scanning", "chunking", "embedding", "ready"];

const STEP_LABELS = {
  uploaded: "Uploaded",
  parsing: "Reading the PDF",
  scanning: "Security scan",
  chunking: "Splitting into clauses",
  embedding: "Indexing",
  ready: "Ready",
};

// After these statuses nothing changes by itself
const FINAL_STATUSES = ["ready", "failed", "quarantined"];

/** Show the processing steps and mark which ones are done. */
function ProgressSteps({ status }) {
  const currentIndex = STEPS.indexOf(status);

  return (
    <ol className="space-y-2">
      {STEPS.map((step, index) => {
        let marker = "○";
        if (status === "ready" || index < currentIndex) {
          marker = "✓";
        } else if (index === currentIndex) {
          marker = "…";
        }

        return (
          <li key={step} className="flex items-center gap-2 text-sm">
            <span className="w-4 text-center">{marker}</span>
            <span>{STEP_LABELS[step]}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** A popup to upload a PDF, follow the processing, and then check the detected details. */
export default function UploadDialog({ onClose }) {
  const [file, setFile] = useState(null);
  const [vendorName, setVendorName] = useState("");
  const [documentType, setDocumentType] = useState("Other");
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isReleasing, setIsReleasing] = useState(false);
  const [error, setError] = useState("");
  const [uploadedDocument, setUploadedDocument] = useState(null);

  // After the upload, ask the backend for the status every 2 seconds until it is finished
  useEffect(() => {
    if (uploadedDocument === null) {
      return;
    }
    if (FINAL_STATUSES.includes(uploadedDocument.status)) {
      return;
    }

    const timer = setInterval(async () => {
      const latest = await getDocument(uploadedDocument.id);
      setUploadedDocument(latest);
    }, 2000);

    return () => clearInterval(timer);
  }, [uploadedDocument]);

  /** Accept the file only if it is a PDF. */
  function chooseFile(newFile) {
    if (!newFile.name.toLowerCase().endsWith(".pdf")) {
      setError("Please choose a PDF file.");
      return;
    }
    setError("");
    setFile(newFile);
  }

  /** Handle a file picked with the file browser. */
  function handleFileInput(event) {
    const pickedFile = event.target.files[0];
    if (pickedFile !== undefined) {
      chooseFile(pickedFile);
    }
  }

  /** Handle a file dropped on the drop area. */
  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    const droppedFile = event.dataTransfer.files[0];
    if (droppedFile !== undefined) {
      chooseFile(droppedFile);
    }
  }

  /** Send the file to the backend. */
  async function handleUpload() {
    if (file === null) {
      return;
    }
    setError("");
    setIsUploading(true);

    try {
      const newDocument = await uploadDocument(file, vendorName.trim(), documentType);
      setUploadedDocument(newDocument);
    } catch (err) {
      setError(err.message);
    }

    setIsUploading(false);
  }

  /** Let a blocked document through after the user confirmed that the sender is trusted. */
  async function handleRelease() {
    const confirmed = window.confirm(
      "Release this document only if you trust the sender. Its instruction-like sentences will still be removed from the text."
    );
    if (!confirmed) {
      return;
    }

    setIsReleasing(true);
    try {
      const released = await releaseDocument(uploadedDocument.id);
      setUploadedDocument(released);
    } catch (err) {
      setError(err.message);
    }
    setIsReleasing(false);
  }

  // Step 3: the document is ready, so the user checks the detected details
  if (uploadedDocument !== null && uploadedDocument.status === "ready") {
    return (
      <Modal title="Check the details" onClose={onClose}>
        <p className="mb-4 text-sm text-green-700">
          {uploadedDocument.file_name} is ready: {uploadedDocument.chunk_count} chunks from{" "}
          {uploadedDocument.page_count} pages (read with {uploadedDocument.parser_used}).
        </p>
        <MetadataForm documentItem={uploadedDocument} useSuggestions={true} onDone={onClose} />
      </Modal>
    );
  }

  // The security scan blocked the document
  if (uploadedDocument !== null && uploadedDocument.status === "quarantined") {
    return (
      <Modal title="Blocked by the security scan" onClose={onClose}>
        <p className="mb-3 text-sm text-gray-600">{uploadedDocument.file_name}</p>
        <div className="rounded border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900">
          {uploadedDocument.error_message}
        </div>
        <p className="mt-3 text-xs text-gray-500">
          Nothing from this document was added to your library. If you trust the sender, you can release it.
        </p>
        {error !== "" && <p className="mt-3 text-sm text-red-600">{error}</p>}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
          <Button variant="danger" onClick={handleRelease} disabled={isReleasing}>
            Release anyway
          </Button>
        </div>
      </Modal>
    );
  }

  // Step 2: the file is uploaded, so show the progress
  if (uploadedDocument !== null) {
    const isFailed = uploadedDocument.status === "failed";

    return (
      <Modal title="Processing your contract" onClose={onClose}>
        <p className="mb-4 text-sm text-gray-600">{uploadedDocument.file_name}</p>
        <ProgressSteps status={uploadedDocument.status} />

        {isFailed && <p className="mt-4 text-sm text-red-600">{uploadedDocument.error_message}</p>}
        <p className="mt-4 text-xs text-gray-500">Scanned pages are read with OCR, which can take a few minutes.</p>

        <div className="mt-6 flex justify-end">
          <Button onClick={onClose}>{isFailed ? "Done" : "Close"}</Button>
        </div>
      </Modal>
    );
  }

  // Step 1: choose the file
  return (
    <Modal title="Upload a contract" onClose={onClose}>
      <label
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={
          "flex cursor-pointer flex-col items-center justify-center rounded border-2 border-dashed p-8 text-sm " +
          (isDragging ? "border-blue-500 bg-blue-50" : "border-gray-300")
        }
      >
        <input type="file" accept="application/pdf" className="hidden" onChange={handleFileInput} />
        {file === null ? (
          <span className="text-gray-600">Drag a PDF here or click to choose one</span>
        ) : (
          <span className="font-medium">{file.name}</span>
        )}
      </label>

      <div className="mt-4 space-y-3">
        <div>
          <label className="mb-1 block text-sm font-medium">Vendor (optional)</label>
          <input
            value={vendorName}
            onChange={(event) => setVendorName(event.target.value)}
            placeholder="Leave empty and we will detect it"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Document type (optional)</label>
          <select
            value={documentType}
            onChange={(event) => setDocumentType(event.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          >
            {DOCUMENT_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error !== "" && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-6 flex items-center justify-end gap-3">
        {isUploading && <Spinner />}
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={handleUpload} disabled={file === null || isUploading}>
          Upload
        </Button>
      </div>
    </Modal>
  );
}