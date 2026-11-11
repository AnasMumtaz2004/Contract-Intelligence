import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  askQuestion,
  clearFocus,
  createConversation,
  getContracts,
  getConversations,
  getDocuments,
  getFocus,
  getMessages,
} from "../api";
import AgentProgress from "../components/AgentProgress";
import AnswerCard from "../components/AnswerCard";
import CitationViewer from "../components/CitationViewer";
import MessageInput from "../components/MessageInput";
import { Button, ErrorBanner, Spinner } from "../components/ui";

/** The chat page: conversation list, message thread, and a panel for the clicked source. */
export default function Chat() {
  const navigate = useNavigate();
  const bottomRef = useRef(null);

  const [contracts, setContracts] = useState([]);
  // How many documents each contract has, like { 3: 2 }
  const [documentCounts, setDocumentCounts] = useState({});
  const [conversations, setConversations] = useState([]);
  const [isStarting, setIsStarting] = useState(true);
  const [activeConversation, setActiveConversation] = useState(null);
  const [messages, setMessages] = useState([]);
  // An empty string means "all contracts"
  const [scopeContractId, setScopeContractId] = useState("");
  // The vendor that follow-up questions are about (empty if there is none)
  const [focusVendor, setFocusVendor] = useState("");
  const [selectedCitation, setSelectedCitation] = useState(null);
  // On small screens the conversation list is hidden until the user asks for it
  const [showSidebar, setShowSidebar] = useState(false);
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

  /** Load the contracts, their document counts and the conversations. */
  async function loadStartData() {
    setIsStarting(true);
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
      setError("");
    } catch (err) {
      setError(err.message);
    }
    await loadConversations();
    setIsStarting(false);
  }

  // Load everything once when the page opens
  useEffect(() => {
    loadStartData();
  }, []);

  // Scroll to the newest message
  useEffect(() => {
    if (bottomRef.current !== null) {
      bottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, progressSteps]);

  /** Open an old conversation and load its messages and its focus. */
  async function openConversation(conversation) {
    setActiveConversation(conversation);
    setSelectedCitation(null);
    setShowSidebar(false);
    setError("");

    try {
      const data = await getMessages(conversation.id);
      setMessages(data);

      const focus = await getFocus(conversation.id);
      setFocusVendor(focus.vendor_name);
    } catch (err) {
      setError(err.message);
    }
  }

  /** Clear the screen so the next question starts a new conversation. */
  function startNewChat() {
    setActiveConversation(null);
    setMessages([]);
    setFocusVendor("");
    setSelectedCitation(null);
    setShowSidebar(false);
    setError("");
  }

  /** Stop focusing on one contract, so the next question searches all contracts. */
  async function handleClearFocus() {
    if (activeConversation === null) {
      return;
    }

    try {
      await clearFocus(activeConversation.id);
      setFocusVendor("");
    } catch (err) {
      setError(err.message);
    }
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
        feedback: null,
        citations: data.citations,
      };
      setMessages((oldMessages) => [...oldMessages, assistantMessage]);
    }

    if (eventName === "focus") {
      setFocusVendor(data.vendor_name);
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

  let sidebarClasses = "hidden md:flex";
  if (showSidebar) {
    sidebarClasses = "flex";
  }

  return (
    <div className="flex h-screen">
      {/* Left: conversation list. On small screens it slides over the page. */}
      <aside className={sidebarClasses + " fixed inset-y-0 left-0 z-20 w-64 flex-col border-r bg-white p-3 md:static"}>
        <div className="mb-3 flex gap-2">
          <Button onClick={startNewChat}>New chat</Button>
          <Button variant="secondary" onClick={() => navigate("/")}>
            Library
          </Button>
        </div>
        <div className="flex-1 space-y-1 overflow-y-auto">
          {isStarting && (
            <div className="flex items-center gap-2 p-2 text-sm text-gray-500">
              <Spinner />
              <span>Loading...</span>
            </div>
          )}
          {!isStarting && conversations.length === 0 && (
            <p className="p-2 text-sm text-gray-500">No conversations yet. Ask your first question.</p>
          )}
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
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b bg-white px-4 py-3 md:px-6">
          <button
            onClick={() => setShowSidebar(!showSidebar)}
            className="rounded border border-gray-300 px-3 py-1 text-sm md:hidden"
          >
            Chats
          </button>

          {activeConversation === null ? (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-gray-600">Search in:</span>
              <select
                value={scopeContractId}
                onChange={(event) => setScopeContractId(event.target.value)}
                className="max-w-full rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="">All contracts</option>
                {contracts.map((contract) => (
                  <option key={contract.id} value={contract.id}>
                    {describeContract(contract)}
                  </option>
                ))}
              </select>
              <span className="hidden text-xs text-gray-500 sm:inline">A contract includes its amendments.</span>
            </div>
          ) : (
            <p className="text-sm text-gray-600">Search in: {getScopeLabel(activeConversation.contract_id)}</p>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4 md:p-6">
          {messages.length === 0 && (
            <p className="mt-10 text-center text-sm text-gray-500">
              Ask a question about your contracts. Every answer shows its sources, and you can click them.
            </p>
          )}

          {messages.map((message) => {
            if (message.role === "user") {
              return (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-xl rounded-lg bg-blue-600 px-4 py-2 text-sm text-white">{message.content}</div>
                </div>
              );
            }
            return <AnswerCard key={message.id} message={message} onCitationClick={setSelectedCitation} />;
          })}

          {isAsking && <AgentProgress steps={progressSteps} />}
          <ErrorBanner message={error} onRetry={isStarting || contracts.length > 0 ? null : loadStartData} />
          <div ref={bottomRef} />
        </div>

        <div className="border-t bg-white p-3 md:p-4">
          <MessageInput
            onSend={handleSend}
            disabled={isAsking}
            focusVendor={focusVendor}
            onClearFocus={handleClearFocus}
          />
        </div>
      </main>

      {/* Right: the clicked source. On small screens it covers the page. */}
      {selectedCitation !== null && (
        <aside className="fixed inset-0 z-30 overflow-y-auto bg-white md:static md:inset-auto md:w-96 md:border-l">
          <CitationViewer citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
        </aside>
      )}
    </div>
  );
}