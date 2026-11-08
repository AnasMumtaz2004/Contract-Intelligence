import { useEffect, useState } from "react";

import { getDocument, uploadDocument } from "../api";
import { Button, Modal, Spinner } from "./ui";

const DOCUMENT_TYPES = ["MSA", "NDA", "SOW", "Amendment", "Exhibit", "Other"];

// The steps a document goes through, in order
const STEPS = ["uploaded", "parsing", "chunking", "embedding", "ready"];

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

        const label = step.charAt(0).toUpperCase() + step.slice(1);
        return (
          <li key={step} className="flex items-center gap-2 text-sm">
            <span className="w-4 text-center">{marker}</span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}

/** A popup to choose a PDF, enter vendor and type, upload it and follow the progress. */
export default function UploadDialog({ onClose }) {
  const [file, setFile] = useState(null);
  const [vendorName, setVendorName] = useState("");
  const [documentType, setDocumentType] = useState("MSA");
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState("");
  const [uploadedDocument, setUploadedDocument] = useState(null);

  // After the upload, ask the backend for the status every 2 seconds until it is finished
  useEffect(() => {
    if (uploadedDocument === null) {
      return;
    }
    if (uploadedDocument.status === "ready" || uploadedDocument.status === "failed") {
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
      const document = await uploadDocument(file, vendorName.trim(), documentType);
      setUploadedDocument(document);
    } catch (err) {
      setError(err.message);
    }

    setIsUploading(false);
  }

  // Step 2: the file is uploaded, so show the progress
  if (uploadedDocument !== null) {
    const isFinished = uploadedDocument.status === "ready" || uploadedDocument.status === "failed";

    return (
      <Modal title="Processing your contract" onClose={onClose}>
        <p className="mb-4 text-sm text-gray-600">{uploadedDocument.file_name}</p>
        <ProgressSteps status={uploadedDocument.status} />

        {uploadedDocument.status === "failed" && (
          <p className="mt-4 text-sm text-red-600">{uploadedDocument.error_message}</p>
        )}
        {uploadedDocument.status === "ready" && (
          <p className="mt-4 text-sm text-green-700">
            Done. {uploadedDocument.chunk_count} chunks created from {uploadedDocument.page_count} pages.
          </p>
        )}

        <div className="mt-6 flex justify-end">
          <Button onClick={onClose}>{isFinished ? "Done" : "Close"}</Button>
        </div>
      </Modal>
    );
  }

  // Step 1: choose the file and enter the details
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
          <label className="mb-1 block text-sm font-medium">Vendor name</label>
          <input
            value={vendorName}
            onChange={(event) => setVendorName(event.target.value)}
            placeholder="For example: Acme Corp"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Document type</label>
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
        <Button onClick={handleUpload} disabled={file === null || vendorName.trim() === "" || isUploading}>
          Upload
        </Button>
      </div>
    </Modal>
  );
}