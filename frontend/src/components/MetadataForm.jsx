import { useEffect, useState } from "react";

import { getDocuments, getSuggestions, updateMetadata } from "../api";
import { Button, Spinner } from "./ui";

const DOCUMENT_TYPES = ["MSA", "NDA", "SOW", "Amendment", "Exhibit", "Other"];

// Documents uploaded without a vendor are stored under this name
const UNASSIGNED_VENDOR = "Unassigned";

/** A form to check and change the vendor, type, effective date and parent of a document. */
export default function MetadataForm({ documentItem, useSuggestions, onDone }) {
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");
  const [allDocuments, setAllDocuments] = useState([]);

  // The form starts with the values the document has now
  let startVendor = documentItem.vendor_name;
  if (startVendor === UNASSIGNED_VENDOR) {
    startVendor = "";
  }
  let startDate = "";
  if (documentItem.effective_date !== null) {
    startDate = documentItem.effective_date;
  }
  let startParent = "";
  if (documentItem.parent_document_id !== null) {
    startParent = String(documentItem.parent_document_id);
  }

  const [vendorName, setVendorName] = useState(startVendor);
  const [documentType, setDocumentType] = useState(documentItem.document_type);
  const [effectiveDate, setEffectiveDate] = useState(startDate);
  const [parentId, setParentId] = useState(startParent);

  // Load the other documents (for the parent list), and the LLM guess if it was asked for
  useEffect(() => {
    async function loadData() {
      try {
        const documents = await getDocuments();
        setAllDocuments(documents);

        if (useSuggestions) {
          const suggestion = await getSuggestions(documentItem.id);
          setVendorName(suggestion.vendor_name);
          setDocumentType(suggestion.document_type);
          if (suggestion.effective_date !== null) {
            setEffectiveDate(suggestion.effective_date);
          }
        }
      } catch (err) {
        setError(err.message);
      }
      setIsLoading(false);
    }

    loadData();
  }, [documentItem.id, useSuggestions]);

  /** List the documents of the chosen vendor that this document can belong to. */
  function getParentOptions() {
    const options = [];
    const wantedVendor = vendorName.trim().toLowerCase();

    for (const item of allDocuments) {
      if (item.id === documentItem.id) {
        continue;
      }
      if (item.vendor_name.toLowerCase() !== wantedVendor) {
        continue;
      }
      options.push(item);
    }
    return options;
  }

  /** List the vendor names that already exist, for the suggestions in the vendor box. */
  function getVendorNames() {
    const names = [];
    for (const item of allDocuments) {
      if (item.vendor_name === UNASSIGNED_VENDOR) {
        continue;
      }
      if (!names.includes(item.vendor_name)) {
        names.push(item.vendor_name);
      }
    }
    return names;
  }

  const parentOptions = getParentOptions();
  const vendorNames = getVendorNames();

  /** Save the details. */
  async function handleSave() {
    if (vendorName.trim() === "") {
      setError("Please enter a vendor name.");
      return;
    }
    setError("");
    setIsSaving(true);

    // The parent must belong to the vendor that is chosen now
    let parentDocumentId = null;
    for (const option of parentOptions) {
      if (String(option.id) === parentId) {
        parentDocumentId = option.id;
      }
    }

    let dateValue = null;
    if (effectiveDate !== "") {
      dateValue = effectiveDate;
    }

    try {
      const updated = await updateMetadata(documentItem.id, {
        vendor_name: vendorName.trim(),
        document_type: documentType,
        effective_date: dateValue,
        parent_document_id: parentDocumentId,
      });
      onDone(updated);
    } catch (err) {
      setError(err.message);
      setIsSaving(false);
    }
  }

  if (isLoading) {
    let loadingText = "Loading...";
    if (useSuggestions) {
      loadingText = "Reading the start of the contract...";
    }
    return (
      <div className="flex items-center gap-2 py-6 text-sm text-gray-600">
        <Spinner />
        <span>{loadingText}</span>
      </div>
    );
  }

  let skipLabel = "Cancel";
  if (useSuggestions) {
    skipLabel = "Skip for now";
  }

  return (
    <div>
      {useSuggestions && (
        <p className="mb-4 text-sm text-gray-600">
          We read the first page and guessed these details. Please check them.
        </p>
      )}

      <div className="space-y-3">
        <div>
          <label className="mb-1 block text-sm font-medium">Vendor</label>
          <input
            list="vendor-names"
            value={vendorName}
            onChange={(event) => setVendorName(event.target.value)}
            placeholder="For example: Acme Corp"
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <datalist id="vendor-names">
            {vendorNames.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
          <p className="mt-1 text-xs text-gray-500">
            Use the same vendor name as the original contract to keep amendments in the same contract.
          </p>
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

        <div>
          <label className="mb-1 block text-sm font-medium">Effective date</label>
          <input
            type="date"
            value={effectiveDate}
            onChange={(event) => setEffectiveDate(event.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
          <p className="mt-1 text-xs text-gray-500">The newest amendment decides the current terms.</p>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium">Belongs to</label>
          <select
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
            className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
          >
            <option value="">Nothing (this is a main contract)</option>
            {parentOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.file_name.split("/").pop()}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-gray-500">For an amendment or exhibit: the contract it changes.</p>
        </div>
      </div>

      {error !== "" && <p className="mt-3 text-sm text-red-600">{error}</p>}

      <div className="mt-6 flex justify-end gap-3">
        <Button variant="secondary" onClick={() => onDone(null)}>
          {skipLabel}
        </Button>
        <Button onClick={handleSave} disabled={isSaving}>
          Save
        </Button>
      </div>
    </div>
  );
}