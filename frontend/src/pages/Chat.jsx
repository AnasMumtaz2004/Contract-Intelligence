import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  askQuestion,
  createConversation,
  getContracts,
  getConversations,
  getDocuments,
  getMessages,
} from "../api";
import AgentProgress from "../components/AgentProgress";
import AnswerCard from "../components/AnswerCard";
import CitationViewer from "../components/CitationViewer";
import MessageInput from "../components/MessageInput";
import { Button } from "../components/ui";

/** The chat page: conversation list, message thread, and a panel for the clicked source. */
export default function Chat() {
  const navigate = useNavigate();
  const bottomRef = useRef(null);

  const [contracts, setContracts] = useState([]);
  // How many documents each contract has, like { 3: 2 }
  const [documentCounts, setDocumentCounts] = useState({});
  const [conversations, setConversations] = useState([]);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  // An empty string means "all contracts"
  const [scopeContractId, setScopeContractId] = useState("");
  const [selectedCitation, setSelectedCitation] = useState(null);
  const [isAsking, setIsAsking] = useState(false);
  // The steps the agent has finished for the current question
  const [progressSteps, setProgressSteps] = useState([]);
  const [error, setError] = useState("");

  /** Load the conversation list from the backend. */
  async function loadConversations() {
    try {
      const data = await getConversations();
      setConversations(data);
    } catch (err) {
      setError(err.message);
    }
  }

  // Load the contracts, their document counts and the conversations once when the page opens
  useEffect(() => {
    async function loadStartData() {
      try {
        const contractData = await getContracts();
        setContracts(contractData);

        const documentData = await getDocuments();
        const counts = {};
        for (const item of documentData) {
          if (!(item.contract_id in counts)) {
            counts[item.contract_id] = 0;
          }
          counts[item.contract_id] += 1;
        }
        setDocumentCounts(counts);
      } catch (err) {
        setError(err.message);
      }
      loadConversations();
    }

    loadStartData();
  }, []);

  // Scroll to the newest message
  useEffect(() => {
    if (bottomRef.current !== null) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, progressSteps]);

  /** Open an old conversation and load its messages. */
  async function openConversation(conversation) {
    setActiveConversation(conversation);
    setSelectedCitation(null);
    setError("");

    try {
      const data = await getMessages(conversation.id);
      setMessages(data);
    } catch (err) {
      setError(err.message);
    }
  }

  /** Clear the screen so the next question starts a new conversation. */
  function startNewChat() {
    setActiveConversation(null);
    setMessages([]);
    setSelectedCitation(null);
    setError("");
  }

  /** Write a contract name with its number of documents, like "Acme Corp (3 documents)". */
  function describeContract(contract) {
    const count = documentCounts[contract.id] ?? 0;
    let word = "documents";
    if (count === 1) {
      word = "document";
    }
    return contract.vendor_name + " (" + count + " " + word + ")";
  }

  /** Get a readable name for the scope of a conversation. */
  function getScopeLabel(contractId) {
    if (contractId === null) {
      return "All contracts";
    }
    const contract = contracts.find((item) => item.id === contractId);
    if (contract === undefined) {
      return "One contract";
    }
    return describeContract(contract);
  }

  /** React to one event from the server. */
  function handleEvent(eventName, data) {
    if (eventName === "step") {
      // The function form adds to the newest list of steps
      setProgressSteps((oldSteps) => [...oldSteps, data.text]);
    }

    if (eventName === "answer") {
      const assistantMessage = {
        id: data.message_id,
        role: "assistant",
        content: data.answer,
        status: data.status,
        warning: data.warning,
        citations: data.citations,
      };
      setMessages((oldMessages) => [...oldMessages, assistantMessage]);
    }

    if (eventName === "error") {
      setError(data.message);
    }
  }

  /** Send a question. The first question also creates the conversation. */
  async function handleSend(question) {
    setError("");
    setIsAsking(true);
    setProgressSteps([]);

    try {
      let conversation = activeConversation;

      if (conversation === null) {
        let contractId = null;
        if (scopeContractId !== "") {
          contractId = Number(scopeContractId);
        }
        // The first 60 letters of the question become the title
        conversation = await createConversation(question.slice(0, 60), contractId);
        setActiveConversation(conversation);
      }

      // Show the question right away
      const userMessage = { id: "temp-" + Date.now(), role: "user", content: question, citations: [] };
      setMessages((oldMessages) => [...oldMessages, userMessage]);

      await askQuestion(conversation.id, question, handleEvent);
    } catch (err) {
      setError(err.message);
    }

    setIsAsking(false);
    setProgressSteps([]);
    loadConversations();
  }

  return (
    <div className="flex h-screen">
      {/* Left: conversation list */}
      <aside className="flex w-64 flex-col border-r bg-white p-3">
        <div className="mb-3 flex gap-2">
          <Button onClick={startNewChat}>New chat</Button>
          <Button variant="secondary" onClick={() => navigate("/")}>
            Library
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {conversations.map((conversation) => {
            let itemColors = "hover:bg-gray-100";
            if (activeConversation !== null && activeConversation.id === conversation.id) {
              itemColors = "bg-blue-50 text-blue-800";
            }
            return (
              <button
                key={conversation.id}
                onClick={() => openConversation(conversation)}
                className={"block w-full truncate rounded px-2 py-2 text-left text-sm " + itemColors}
              >
                {conversation.title}
              </button>
            );
          })}
        </div>
      </aside>

      {/* Middle: messages and input */}
      <main className="flex flex-1 flex-col">
        <div className="flex items-center justify-between border-b bg-white px-6 py-3">
          {activeConversation === null ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-gray-600">Search in:</span>
              <select
                value={scopeContractId}
                onChange={(event) => setScopeContractId(event.target.value)}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="">All contracts</option>
                {contracts.map((contract) => (
                  <option key={contract.id} value={contract.id}>
                    {describeContract(contract)}
                  </option>
                ))}
              </select>
              <span className="text-xs text-gray-500">A contract includes its amendments.</span>
            </div>
          ) : (
            <p className="text-sm text-gray-600">Search in: {getScopeLabel(activeConversation.contract_id)}</p>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {messages.length === 0 && (
            <p className="mt-10 text-center text-sm text-gray-500">
              Ask a question about your contracts. Every answer shows its sources, and you can click them.
            </p>
          )}

          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-xl rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">
                    {message.content}
                  </div>
                </div>
              );
            }
            return <AnswerCard key={message.id} message={message} onCitationClick={setSelectedCitation} />;
          })}

          {isAsking && <AgentProgress steps={progressSteps} />}
          {error !== "" && <p className="text-sm text-red-600">{error}</p>}
          <div ref={bottomRef} />
        </div>

        <div className="border-t bg-white p-4">
          <MessageInput onSend={handleSend} disabled={isAsking} />
        </div>
      </main>

      {/* Right: the clicked source */}
      {selectedCitation !== null && (
        <aside className="w-96 overflow-y-auto border-l bg-white">
          <CitationViewer citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
        </aside>
      )}
    </div>
  );
}