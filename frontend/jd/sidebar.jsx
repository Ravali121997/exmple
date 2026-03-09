"use client";
import React, { useState, useEffect,useRef } from "react";
import axios from "axios";
import { FaSyncAlt } from "react-icons/fa";
export default function Sidebar({
  jdId,
  roles,
  skills_data,
  sendRangeValue,
  onCreate,
  sendSelectedRoles,
  selectedDashboardId,
  analysisData,
  resumeData,
}) {
    console.log("📦 Sidebar Props Received:", {jdId,selectedDashboardId,analysisData,resumeData,});
  const [prompt, setPrompt] = useState("");
  const [rangeValue, setRangeValue] = useState(1);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState(null);
  const [samplePrompts, setSamplePrompts] = useState([]);
  const [selectedSamplePrompt, setSelectedSamplePrompt] = useState("");
  const [history, setHistory] = useState([]);
  const [activeTab, setActiveTab] = useState("sample");
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // const [resumeData, setResumeData] = useState(null); 
  const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
  
   const cacheKey = `samplePrompts_${jdId}`;
   
   useEffect(() => {
        console.log("🟢 jdId from analysisData in Sidebar:", analysisData?.job_id);
    }, [analysisData]);
    useEffect(() => {
    console.log("🟢 Sidebar detected analysisData update:", analysisData);
    }, [analysisData]);

    useEffect(() => {
        if (resumeData) {
            console.log("📄 Sidebar received resumeData:", resumeData);
        }
        }, [resumeData]);
  // 🔹 Load sample prompts + local prompt history
   const fetchSamplePrompts = async (forceRefresh = false) => {
    if (!jdId) return;

    // 1️⃣ If NOT forcing refresh → try cache first
    if (!forceRefresh) {
      const cached = localStorage.getItem(cacheKey);
      if (cached) {
        console.log("📁 Loaded sample prompts from cache");
        setSamplePrompts(JSON.parse(cached));
        return;
      }
    }

    // 2️⃣ Fetch from backend
    try {
      console.log("🌐 Fetching fresh prompts from backend...");
      setIsLoading(true);
      setError(null);
      
      const token = localStorage.getItem("authToken"); 
      const res = await axios.get(`${API_BASE_URL}/sample_prompts/${jdId}`);

      let prompts = [];
      if (Array.isArray(res.data)) prompts = res.data;
      else if (res.data?.sample_prompts) prompts = res.data.sample_prompts;

      setSamplePrompts(prompts);

      // 3️⃣ Save to localStorage cache
      localStorage.setItem(cacheKey, JSON.stringify(prompts));
      console.log("💾 Saved new prompts to cache");

    } catch (err) {
      console.error("❌ Error fetching prompts:", err);
      setError("Failed to load sample prompts.");
    } finally {
      setIsLoading(false);
    }
  };

  // ---------------------------------------
  // Fetch prompts when JD loads (only once)
  // ---------------------------------------
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (!jdId || hasFetchedRef.current) return;
    hasFetchedRef.current = true;

    fetchSamplePrompts(false);
  }, [jdId]);
  // useEffect(() => {
  //   fetchSamplePrompts(false); // not forced → uses cache first
  // }, [jdId]);

  const fetchPromptHistory = () => {
    try {
      const localKey = `promptHistory_${jdId}`;
      const saved = JSON.parse(localStorage.getItem(localKey)) || [];
      setHistory(saved);
    } catch {
      setHistory([]);
    }
  };

  // --- 🆕 CREATE DASHBOARDS (via slider) ---
  const handleCreateDashboard = (e) => {
    if (e?.preventDefault) e.preventDefault();
    setIsCreating(true);

    const scale = Math.min(10, Math.max(1, Number(rangeValue) || 1));
    window.dispatchEvent(new CustomEvent("createDashboards_jd", { detail: { scale } }));

    if (onCreate) onCreate({ createScale: scale, append: false });
     setIsCreating(false);
  };

// const handleCreateDashboard = (e) => {
//   if (e?.preventDefault) e.preventDefault();

//   setIsCreating(true);

//   const scale = Math.min(10, Math.max(1, Number(rangeValue) || 1));

//   setTimeout(() => {
//     window.dispatchEvent(
//       new CustomEvent("createDashboards_jd", { detail: { scale } })
//     );

//     if (onCreate) onCreate({ createScale: scale, append: false });

//     setIsCreating(false);
//   }, 300);
// };

  // --- 🧠 SUBMIT PROMPT (create or modify dashboard) ---
  const handleSubmitPrompt = (e) => {
    if (e?.preventDefault) e.preventDefault();

    const text = (selectedSamplePrompt || prompt || "").trim();
    if (!text) {
      alert("Please enter or select a prompt before submitting.");
      return;
    }

    setIsCreating(true);

    // const isAppend = !selectedDashboardId;
    // const dashboardId = selectedDashboardId || null;
    // Inside handleSubmitPrompt

    console.log("🧭 Sidebar received selectedDashboardId prop:", selectedDashboardId);
    const dashboardIdToUse = selectedDashboardId || null;

    if (dashboardIdToUse) {
      console.log("🛠 Modifying dashboard with ID:", dashboardIdToUse);
    } else {
      console.log("➕ No dashboard selected — will append a new dashboard");
    }
    const isAppend = dashboardIdToUse === null;

    console.log("🚀 Prompt submitted:", {
      text,
      jdId,
      selectedDashboardId,
      isAppend,
    });
    
    console.log("💡 Sidebar will pass analysisData to parent onCreate:", analysisData);

    // 🔹 Pass to Sample.jsx (React callback)
    if (onCreate) {
      onCreate({
        prompt: text,
        append: isAppend,
        dashboardId:dashboardIdToUse,
      });
    }

     // 🔹 Dispatch a CustomEvent for any listener
    window.dispatchEvent(
      new CustomEvent("promptSubmit_jd", {
        detail: {
          prompt: text,
          dashboardId:dashboardIdToUse, // ✅ include selectedDashboardId here
          jdId,
          // append: isAppend,
        },
      })
    );
    // 🔹 Save to local storage history
    const localKey = `promptHistory_${jdId}`;
    const existing = JSON.parse(localStorage.getItem(localKey)) || [];
    const updated = [text, ...existing.filter((p) => p !== text)].slice(0, 10);
    localStorage.setItem(localKey, JSON.stringify(updated));
    fetchPromptHistory();

    // Reset UI state
    setPrompt("");
    setSelectedSamplePrompt("");
    setIsCreating(false);
  };

  return (
    <div style={styles.outerContainer}>
      {/* Range Slider */}
      <div style={{ paddingTop: "1px" }}>
        <input
          type="range"
          min="1"
          max="10"
          value={rangeValue}
          onChange={(e) => setRangeValue(Number(e.target.value))}
          style={styles.slider}
        />
        <p className="text-sm mt-1">Number of Dashboards: {rangeValue}</p>
      </div>

      {/* Create Button */}
      <button
        type="button"
        onClick={handleCreateDashboard}
        style={{
          ...styles.createButton,
          opacity: isCreating ? 0.7 : 1,
          cursor: isCreating ? "wait" : "pointer",
        }}
        disabled={isCreating}
      >
        {isCreating ? "Creating..." : "Create Dashboard"}
      </button>

      {error && (
        <div className="mt-1 p-2 bg-red-50 text-red-700 rounded-md border border-red-200 text-xs">
          {error}
        </div>
      )}

      {/* Prompt Input */}
      <div className="mt-1">
        <div className="flex justify-between items-center">
          <label className="block text-sm font-medium text-gray-700">
            Custom Prompt
          </label>
         {/* Clear Button */}
          <button
            onClick={() => setPrompt("")}
            className="text-xs px-2 py-1 bg-gray-200 hover:bg-gray-300 rounded-md"
          >
            Clear
          </button>
        </div>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="w-full p-2 border-2 rounded-md text-sm min-h-[50px] placeholder-gray-400 mt-2"
          placeholder={
            selectedDashboardId
              ? "Modify selected dashboard..."
              : "Enter prompt to create dashboard..."
          }
        />
      </div>

      {/* Submit Button */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "1px" }}>
        <button
          type="button"
          onClick={handleSubmitPrompt}
          disabled={isSubmitting}
          style={{
            padding: "8px 10px",
            backgroundColor: "#6200ea",
            color: "white",
            border: "none",
            borderRadius: "4px",
            cursor: isSubmitting  ? "wait" : "pointer",
            fontWeight: "600",
            fontSize: "14px",
            minWidth: "80px",  
          }}
        >
          {isSubmitting  ? "Submitting..." : "Submit"}
        </button>
      </div>

      {/* ✅ SAMPLE PROMPTS / HISTORY SECTION */}
      <div className="mt-2">
        {/* Tabs + Refresh Row */}
        <div className="flex items-center bg-gray-100 rounded-lg mb-3 p-1">
          <button
            onClick={() => setActiveTab("sample")}
            className={`flex-1 whitespace-nowrap text-center py-2 rounded-md font-medium transition ${
              activeTab === "sample"
                ? "bg-indigo-500 text-white"
                : "text-gray-700 hover:bg-indigo-50"
            }`}
          >
            Sample Prompts
          </button>

          <button
            onClick={() => {
              localStorage.removeItem(cacheKey); // clear cache
              fetchSamplePrompts(true); // force refresh
            }}
            className="mx-2 text-gray-600 hover:text-indigo-600 transition flex items-center justify-center"
            title="Refresh Prompts"
            disabled={isLoading}
            style={{ cursor: isLoading ? "wait" : "pointer" }}
          >
            {/* {isLoading ? "Refreshing..." : <FaSyncAlt size={16} />} */}
            <FaSyncAlt size={16} />
          </button>

          <button
            onClick={() => setActiveTab("history")}
            className={`flex-1 whitespace-nowrap text-center py-2 rounded-md font-medium transition ${
              activeTab === "history"
                ? "bg-indigo-500 text-white"
                : "text-gray-700 hover:bg-indigo-50"
            }`}
          >
            History
          </button>
        </div>

        {/* Tab Content */}
        {activeTab === "sample" ? (
          <div className="flex flex-col w-full">
            {isLoading && (
              <p className="text-sm text-gray-500 mb-2">
                Refreshing...
              </p>
            )}
            {samplePrompts.length > 0 ? (
              <ol className="list-decimal list-inside space-y-0">
                {samplePrompts.slice(0, 10).map((item, index) => (
                  <li
                    key={index}
                    className="cursor-pointer hover:bg-indigo-50 rounded-md px-3 py-1 transition text-sm text-slate-800"
                    onClick={() => setPrompt(typeof item === "string" ? item : item.text)}
                  >
                    {typeof item === "string" ? item : item.text}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-gray-500 italic mt-2">
                No sample prompts available yet.
              </p>
            )}
          </div>
        ) : (
          <div className="bg-gray-50 rounded-md max-h-[200px] overflow-y-auto">
            {history.length > 0 ? (
              history.map((h, i) => (
                <div
                  key={i}
                  className="p-2 bg-white cursor-pointer hover:bg-indigo-50 text-sm transition"
                  onClick={() => setPrompt(h)}
                >
                  {h}
                </div>
              ))
            ) : (
              <p className="text-xs text-gray-500 italic p-3">No history yet.</p>
            )}
          </div>
        )}
      </div>


      {/* Resume Info (optional) */}
     <div className="mt-4 p-3 bg-gray-50 rounded-md border border-gray-200">
      <h3 className="text-sm font-semibold mb-2">Resume Information</h3>
      <div className="text-xs space-y-1">
        <p>
          <span className="font-medium">Name:</span>{" "}
          {resumeData?.candidateName || "N/A"}
        </p>
        <p>
          <span className="font-medium">Role:</span>{" "}
          {resumeData?.role || "N/A"}
        </p>
        <p>
          <span className="font-medium">Email:</span>{" "}
          {resumeData?.email || "N/A"}
        </p>
        </div>
      </div>    
    </div>
  );
}

const styles = {
  outerContainer: {
    padding: "10px",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    maxWidth: "600px",
    margin: "0 auto",
  },
  slider: {
    width: "100%",
    marginBottom: "10px",
  },
  createButton: {
    padding: "8px 14px",
    backgroundColor: "#6200ea",
    color: "white",
    border: "none",
    borderRadius: "8px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: "600",
    transition: "background-color 0.3s ease",
  },
};
