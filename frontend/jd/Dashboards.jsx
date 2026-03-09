"use client";
import React, { useState, useEffect, useRef, useCallback } from "react";
import PropTypes from "prop-types";
import { toast } from 'react-toastify';
import { X, ChevronsRight, Mic, StopCircle, Trash } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  PieChart, Pie, Cell,
  BarChart, Bar,
  LineChart, Line,
  AreaChart, Area,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer
} from 'recharts';
/* ---------------------- Chart Utilities ---------------------- */
const COLORS = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6"];


const parseData = (content) => {
  if (!content) {
    return [{ name: 'No Data', value: 100 }];
  }

  // Normalize input
  let lines = [];
  if (Array.isArray(content)) {
    lines = content.filter(line => typeof line === 'string' && line.trim());
  } else if (typeof content === 'object') {
    if (Array.isArray(content.overview)) {
      lines = content.overview.filter(line => typeof line === 'string' && line.trim());
    } else {
      lines = Object.values(content)
        .flatMap(v => (Array.isArray(v) ? v : [v]))
        .filter(line => typeof line === 'string' && line.trim());
    }
  } else if (typeof content === 'string') {
    lines = content.split('\n').filter(line => line.trim());
  }

  if (lines.length === 0) {
    return [{ name: 'No Data', value: 100 }];
  }

  // Importance scoring
  const scores = lines.map(line => {
    const lengthScore = Math.min(line.length / 100, 1);
    const keywordScore = (line.match(/\b(skill|experience|project|knowledge|expert|strong|good|proficient|excellent)\b/gi) || []).length * 0.5;
    const total = lengthScore + keywordScore + 0.5;
    return total;
  });

  // Normalize to 100%
  const totalScore = scores.reduce((a, b) => a + b, 0);
  const normalized = scores.map(s => (s / totalScore) * 100);

  // Return chart data
  return lines.map((line, idx) => ({
    name: line.length > 15 ? line.substring(0, 15) + '...' : line,
    value: parseFloat(normalized[idx].toFixed(1)),
    amt: parseFloat((normalized[idx] * 0.8).toFixed(1)),
    pv: parseFloat((normalized[idx] * 1.2).toFixed(1)),
    uv: parseFloat((normalized[idx] * 0.9).toFixed(1)),
  }));
};

// Parses Q&A content from API response into structured pairs
const parseQAContent = (content) => {
  if (!content || typeof content !== 'string') return [];
  const lines = content.split('\n').filter(line => line.trim());
  const qaArray = [];
  let currentQ = '';
  let currentA = '';
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.match(/^Q\d*[:.]/i)) {
      if (currentQ && currentA) qaArray.push({ question: currentQ, answer: currentA });
      currentQ = line.replace(/^Q\d*[:.]\s*/i, '').trim();
      currentA = '';
    } else if (line.match(/^A\d*[:.]/i)) {
      currentA = line.replace(/^A\d*[:.]\s*/i, '').trim();
    } else if (currentA) {
      currentA += ' ' + line;
    } else if (currentQ) {
      currentQ += ' ' + line;
    }
  }
  if (currentQ && currentA) qaArray.push({ question: currentQ, answer: currentA });
  return qaArray;
};

const DashboardChart = React.memo(({ content, type }) => {
   // 🔍 Runtime validation
  if (typeof content !== 'string') {
    console.warn('⚠️ DashboardChart: Invalid content type:', typeof content, content);
  }
  const data = React.useMemo(() => {
    //  console.log('Parsing data...');
  return parseData(content);
}, [content]);

  const renderChart = React.useCallback(() => {
    // console.log('Rendering chart...');
    
    switch (type) {
      case 'pie':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" labelLine={false} outerRadius={120} fill="#8884d8" dataKey="value">
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );
      case 'donut':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <PieChart>
              <Pie data={data} cx="45%" cy="45%" innerRadius={60} outerRadius={120} fill="#8884d8" dataKey="value">
                {data.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );
      case 'bar':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <BarChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="value" fill="#8884d8" />
            </BarChart>
          </ResponsiveContainer>
        );
      case 'line':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="value" stroke="#8884d8" />
            </LineChart>
          </ResponsiveContainer>
        );
      case 'area':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <AreaChart data={data}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Area type="monotone" dataKey="value" stroke="#8884d8" fill="#8884d8" />
            </AreaChart>
          </ResponsiveContainer>
        );
      case 'radar':
        return (
          <ResponsiveContainer width="100%" height={400}>
            <RadarChart data={data}>
              <PolarGrid />
              <PolarAngleAxis dataKey="name" />
              <PolarRadiusAxis />
              <Radar dataKey="value" stroke="#8884d8" fill="#8884d8" fillOpacity={0.6} />
              <Legend />
            </RadarChart>
          </ResponsiveContainer>
        );
      default:
        return null;
    }
  }, [data, type]);

  return <div className="w-full h-full">{renderChart()}</div>;
}, (prevProps, nextProps) => {
  return prevProps.content === nextProps.content && JSON.stringify(prevProps.content) === JSON.stringify(nextProps.content); // 
});




/* ---------------------- Main Component ---------------------- */

export default function Dashboard({
  analysisData,
  hasGeneratedDashboard,
  selectedDashboardId,
  setSelectedDashboardId,
  selectedFile,
}) {
  const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
 
  const [dashboards, setDashboards] = useState([]);
  const [selectedDashboardIndex, setSelectedDashboardIndex] = useState(null);
  const [selectedDashboardContent, setSelectedDashboardContent] =useState(null);
  const [activeTab, setActiveTab] = useState(null);
  const [dashboardHistory, setDashboardHistory] = useState([]);
  const [expandedDashboard, setExpandedDashboard] = useState(null);
  const [generatedQA, setGeneratedQA] = useState([]);
  const [qaContents, setQaContents] = useState({}); 
  const [qaHistory, setQaHistory] = useState([]);
  const [recordedQA, setRecordedQA] = useState(null);
  const [evaluation, setEvaluation] = useState(null);
  const [activeView, setActiveView] = useState(null);
  const [dashboardTitles, setDashboardTitles] = useState([]);
  const [sliderValue, setSliderValue] = useState(5);
  const [displayedQuestions, setDisplayedQuestions] = useState([]);
  const [expandedQuestions, setExpandedQuestions] = useState(new Set());
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState(null);
  const [hasInteracted, setHasInteracted] = useState(false);
  const [isInitialView, setIsInitialView] = useState(true);
  const [dashboardIds, setDashboardIds] = useState([]);
  const [eventScale, setEventScale] = useState(1);
  const [eventPrompt, setEventPrompt] = useState("");
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [followUpQuestions, setFollowUpQuestions] = useState([]);
  const [nestedFollowUps, setNestedFollowUps] = useState({}); // Store follow-ups per question ID
  const [difficulty, setDifficulty] = useState("beginner");
  const [qaGenerationSettings] = useState({ // If not used to update settings from UI, can be simple const
    numQuestions: 5,
    difficulty: 'medium'
  });
  const [isGeneratingQA, setIsGeneratingQA] = useState(false);
  const [candidateName] = useState('Unknown Candidate'); // No setter used, consider if fixed or needs update
  const [currentQuestionText, setCurrentQuestionText] = useState(''); // Live transcription for Interviewer
  const [currentAnswerText, setCurrentAnswerText] = useState(''); // Live transcription for Candidate
  const [isRecording, setIsRecording] = useState(false); // Indicates actual audio recording status
  const [sessionId, setSessionId] = useState(null); // Backend session ID
  const [audioLevel, setAudioLevel] = useState(0); // Real-time audio input level
  const [currentSessionId, setCurrentSessionId] = useState(null); // Matches sessionId after start_recording
  const [micPermissionStatus, setMicPermissionStatus] = useState(null);
  const [timer, setTimer] = useState('00:00:00'); // Used for recording time display
  const [recordingState, setRecordingState] = useState('idle');
  const [promptDashboard, setPromptDashboard] = useState('');
  
  // Refs for Web Audio API and transcript scrolling
  const transcriptContainerRef = useRef(null); // For live scrolling
  const wsRef = useRef(null); // WebSocket connection reference
  const audioContextRef = useRef(null); // Web Audio API context
  const processorRef = useRef(null); // AudioWorkletNode or ScriptProcessorNode
  const systemSourceRef = useRef(null); // MediaStreamSource for system audio
  const micSourceRef = useRef(null); // MediaStreamSource for microphone audio
  const streamRef = useRef(null); // MediaStream for system audio
  const micStreamRef = useRef(null); // MediaStream for microphone audio
  const mixerNodeRef = useRef(null); // GainNode to mix audio sources
  const analyserRef = useRef(null); // AnalyserNode for audio level monitoring
  const animationFrameRef = useRef(null); // For audio level visualization loop
  const recordingIntervalRef = useRef(null);
 const [collapsedFollowUpSections, setCollapsedFollowUpSections] = useState(new Set());
 
    // Reset Q&A related state whenever the active dashboard/view changes.
  useEffect(() => {
    // Whenever a new dashboard is selected or we switch views, clear Q&A so
    // generated questions/answers from the previous dashboard don't persist.
    const resetQAState = () => {
      setGeneratedQA([]);
      setDisplayedQuestions([]);
      setQaContents({});
      setQaHistory([]);
      setQaContents(null);
      setRecordedQA(null);
      setEvaluation(null);
      setScore({ correct: 0, total: 0 });
      setExpandedQuestions(new Set());
      // Also clear follow-up questions when switching dashboards/views
      setFollowUpQuestions([]);
      setNestedFollowUps({});
       setCollapsedFollowUpSections(new Set());
    };

    // Run reset when selectedDashboardIndex or expandedDashboard or activeView changes
    resetQAState();

    // Note: we intentionally do not add all setter functions to deps; we only
    // want the effect to run when dashboard/view selection changes.
  }, [selectedDashboardIndex, expandedDashboard, activeView]);

  // // Recording handlers
  // const handleStartRecording = async () => {
  //   try {
  //     const session_id = await startRecordingAPI('candidate');
  //     setCurrentSessionId(session_id);
  //     setRecordingState('recording');
  //     setIsRecording(true);
  //     toast.success('Recording started');
  //   } catch (error) {
  //     console.error('Failed to start recording:', error);
  //     toast.error('Failed to start recording');
  //   }
  // };

  // const handleStopRecording = async () => {
  //   try {
  //     if (currentSessionId) {
  //       await stopRecordingAPI(currentSessionId);
  //       setCurrentSessionId(null);
  //       setRecordingState('idle');
  //       setIsRecording(false);
  //       toast.success('Recording stopped');
  //     }
  //   } catch (error) {
  //     console.error('Failed to stop recording:', error);
  //     toast.error('Failed to stop recording');
  //   }
  // };

  // // Evaluation handler
  // const handleEvaluateQA = async () => {
  //   if (qaHistory.length === 0) {
  //     toast.warn('No Q&A to evaluate');
  //     return;
  //   }

  //   try {
  //     const response = await fetch(`${API_BASE_URL}/evaluate_QA`, {
  //       method: 'POST',
  //       headers: {
  //         'Content-Type': 'application/json',
  //       },
  //       body: JSON.stringify({
  //         interview_text: qaHistory.map(item => `Q: ${item.question}\nA: ${item.answer}`).join('\n\n')
  //       }),
  //     });

  //     if (!response.ok) {
  //       throw new Error(`HTTP error! status: ${response.status}`);
  //     }

  //     const data = await response.json();
  //     setEvaluation(data);
  //     toast.success('Evaluation completed');
  //   } catch (error) {
  //     console.error('Error evaluating Q&A:', error);
  //     toast.error('Failed to evaluate Q&A');
  //   }
  // };

  // useEffect(() => {
  //   let timerInterval = null;
  //   if (recordingState === 'recording') {
  //     const startTime = Date.now();
  //     timerInterval = setInterval(() => {
  //       const elapsed = Date.now() - startTime;
  //       const formattedTime = formatTime(elapsed);
  //       setTimer(formattedTime); // Updates the timer state
  //     }, 1000);
  //   } else {
  //     setTimer('00:00:00'); // Resets timer when not recording
  //   }
  //   return () => {
  //     if (timerInterval) clearInterval(timerInterval);
  //   };
  // }, [recordingState]);

  useEffect(() => {
    if (transcriptContainerRef.current) {
      transcriptContainerRef.current.scrollTop = transcriptContainerRef.current.scrollHeight;
    }
  }, [qaHistory]); // Re-runs whenever qaHistory updates

  const formatTime = (ms) => {
    const seconds = Math.floor((ms / 1000) % 60);
    const minutes = Math.floor((ms / (1000 * 60)) % 60);
    const hours = Math.floor((ms / (1000 * 60 * 60)) % 24);
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };

  // const startRecordingAPI = async (role) => {
  //   const response = await fetch(`${API_BASE_URL}/start_recording`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ role }) });
  //   if (!response.ok) throw new Error('Failed to start recording session');
  //   const data = await response.json();
  //   return data.session_id;
  // };

  // const stopRecordingAPI = async (id) => { // Renamed sessionId to id for consistency with above
  //   const response = await fetch(`${API_BASE_URL}/stop_recording/${id}`, { method: 'POST', headers: { 'Content-Type': 'application/json' } });
  //   if (!response.ok) throw new Error('Failed to stop recording session');
  //   return await response.json();
  // };

  useEffect(() => {
      if (!jobId) {
        console.warn("🚫 Cannot dispatch createDashboards_jd — jobId not ready");
        return;
      }
      // Handle dashboard creation
      const handleCreate = async (e) => {
        const { scale } = e.detail;
        console.log("📥 createDashboards_jd event received:", scale);
        console.log("🧩 Current jobId before generating dashboard:", jobId);
        setEventScale(scale);

        await handleCreateDashboards(scale);
  
      };

      // Handle prompt submission
    const handlePrompt = async (e) => {
      const { prompt, append, dashboardId: eventDashboardId } = e.detail;
      console.log("📥 promptSubmit_jd CALLED", e.detail);

      setEventPrompt(prompt);

      if (!jobId) {
        console.warn("❗JD not uploaded yet — skipping prompt generation");
        return;
      }

      // Use backend ID directly — the frontend ID mapping is unnecessary now
      const backendId = eventDashboardId || selectedDashboardId;
      const shouldAppend = append || !backendId;

      if (shouldAppend) {
        console.log("➕ Appending new dashboard for prompt");
        // handleRunPrompt returns backend ID
        const newBackendId = await handleRunPrompt(prompt);

        // Directly set the selectedDashboardId to the backend ID
        setSelectedDashboardId(newBackendId);
        
      } else {
        console.log("🛠 Modifying existing dashboard with backend ID:", backendId);
        await handleModifyDashboard(prompt, backendId);
      }
    };

      console.log("✅ jobId is ready — adding event listeners");
      window.addEventListener("createDashboards_jd", handleCreate);
      window.addEventListener("promptSubmit_jd", handlePrompt);

      return () => {
        console.log("🧹 Cleaning up RightSidebar event listeners");
        window.removeEventListener("createDashboards_jd", handleCreate);
        window.removeEventListener("promptSubmit_jd", handlePrompt);
      };
    }, [jobId, selectedDashboardId]);

  // Effect for initial data processing on mount or when dependencies change
  const hasInteractedRef = useRef(hasInteracted);
  useEffect(() => {
    if (analysisData && !hasInteractedRef.current) {
      console.log('🧩 analysisData received:', analysisData);

      const extractedJobId = analysisData.job_id || analysisData.file?.job_id || analysisData.file?.id || null;
      console.log("🧩 Extracted jobId:", extractedJobId);
      console.log("📦 analysisData in useEffect:", analysisData);
      setJobId(extractedJobId);

      const { dashboardContent, dashboardContents, content } = analysisData;
         console.log("📊 dashboardContents:", dashboardContents);
         console.log("📈 dashboardContent:", dashboardContent);
         console.log("📄 Raw content:", content);

      if (Array.isArray(dashboardContents) && dashboardContents.length > 0) {
        setDashboards(dashboardContents);
        setDashboardTitles(dashboardContents.map((_, i) => `Dashboard ${i + 1}`));
        setSelectedDashboardIndex(0);
        setSelectedDashboardContent(dashboardContents[0]);
//       if (Array.isArray(dashboardContents) && dashboardContents.length > 0) {
//     setDashboards(dashboardContents);

//     // Use backend titles if available, fallback to "Dashboard X"
//     setDashboardTitles(
//         dashboardContents.map((d, i) => d.dashboard_title || `Dashboard ${i + 1}`)
//     );

//     setSelectedDashboardIndex(0);

//     // Make a shallow copy to avoid duplicate object reference
//     setSelectedDashboardContent({ ...dashboardContents[0] });
// }
      } else if (hasGeneratedDashboard && dashboardContent) {
        setDashboards([dashboardContent]);
        setDashboardTitles(["Dashboard 1"]);
        setSelectedDashboardIndex(0);
        setSelectedDashboardContent(dashboardContent);
      } else if (content) {
        setDashboards([content]);
        setDashboardTitles(["Raw JD"]);
        setSelectedDashboardIndex(0);
        setSelectedDashboardContent(content);
      } else {
        // 🚨 No content found
        console.warn("⚠️ No dashboard or content found in analysisData");
        setDashboards([]);
        setDashboardTitles([]);
        setSelectedDashboardIndex(null);
        setSelectedDashboardContent(null);
      }
      hasInteractedRef.current = true;
    }
  }, [analysisData, hasGeneratedDashboard]);

    
  useEffect(() => {
    if (!selectedDashboardId) {
      setSelectedDashboardContent(null);
      setSelectedDashboardIndex(null);
      return;
    }
    const foundDashboardIndex = dashboards.findIndex(d => d.dashboard_id === selectedDashboardId);
    const foundDashboard = dashboards.find(d => d.dashboard_id === selectedDashboardId);
    setSelectedDashboardIndex(foundDashboardIndex);
    setSelectedDashboardContent(foundDashboard || null);
  }, [selectedDashboardId, dashboards]);



   //fetches dashboards from backend using jobId
  // 1) Create N dashboards (auto) - uses job_id returned after upload
  const handleCreateDashboards = async (count = 1) => {
     console.log("🔔 handleCreateDashboards called with count:", count);
    if (!jobId) {
      setError('No job_id found. Upload the JD first.');
      return;
    }
    
    console.log("📥 createDashboards event received:", count, "with jobId:", jobId);
    setIsLoading(true);
    setError('');

    try {
      console.log("🔔 About to fetch to backend:", `${API_BASE_URL}/auto_generate/${jobId}?count=${count}`);
      const res = await fetch(`${API_BASE_URL}/auto_generate/${jobId}?count=${count}`, {
        method: 'POST',
      });

      if (!res.ok) {
        const err = await res.text();
        throw new Error(`Auto-generate failed: ${res.status} ${err}`);
      }

      const data = await res.json();
      setHasInteracted(true);
      const dashboardsCreated = data.dashboards || [];

      // Create structured dashboard content for UI
      const structured = dashboardsCreated.map((d) => ({
        dashboard_id: d.dashboard_id,
        dashboard_title: d.dashboard_title,
        overview: d.overview
      }));
      
      
      setDashboards(structured);
      setDashboardIds(structured.map(d => d.dashboard_id));
      setDashboardTitles(structured.map(d => d.dashboard_title));

      // Select the first one
      // setSelectedDashboardIndex(0);
      // setSelectedDashboardContent(structured[0]);
      if (structured.length > 0) {
        setSelectedDashboardIndex(0);
        setSelectedDashboardContent(structured[0]);
        setSelectedDashboardId(structured[0].dashboard_id);
      }
      setActiveTab('overview');
      setIsInitialView(false);

      console.log("📊 Dashboards ready:", structured);
    } catch (err) {
      console.error(err);
      setError(err.message || 'Dashboard generation failed');
    } finally {
      setIsLoading(false);
    }
  };

  // 2) Create one dashboard from a prompt (append) — backend returns content in data.data
  
  const handleRunPrompt = async (promptText) => {
    if (!jobId || !promptText) return;

    setIsLoading(true);
    setError("");

    try {
      console.log("🚀 Creating new dashboard from custom prompt...");
      const res = await fetch(`${API_BASE_URL}/custom_prompt/${jobId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText }),
      });

      if (!res.ok) throw new Error(`Prompt failed: ${res.status}`);

      const json = await res.json();
      const returned = json.data || {};
      const dashboardId = returned.dashboard_id;
      const dashboardContent = returned.content || {};
      dashboardContent.dashboard_id = dashboardId;

      // Append in frontend state
      setDashboards(prev => {
        const newDashboards = [...prev, dashboardContent];
        setSelectedDashboardIndex(newDashboards.length - 1);
        setSelectedDashboardContent(dashboardContent);
        return newDashboards;
      });

      setDashboardIds(prev => [...prev, dashboardId]);
      setDashboardTitles(prev => [...prev, dashboardContent.dashboard_title || `Dashboard ${dashboards.length + 1}`]);
      setSelectedDashboardId(dashboardId);
      setActiveTab("overview");
      setIsInitialView(false);
     
      console.log("✅ New dashboard created from prompt:", dashboardContent);
      return dashboardId;
    } catch (err) {
      console.error(err);
      setError(err.message || "Prompt generation failed");
    } finally {
      setIsLoading(false);
    }
  };


  // Modify an existing dashboard using a prompt
  
  const handleModifyDashboard = async (modificationPrompt, dashboardId = selectedDashboardId) => {
    if (!dashboardId) {
      setError("Please select a dashboard before modifying.");
      console.warn("⚠️ Missing dashboardId for modification");
      return;
    }

    const index = dashboards.findIndex((d) => d.dashboard_id === dashboardId);
    if (index === -1) {
      setError("Dashboard not found in frontend state.");
      console.warn("⚠️ Dashboard not found:", dashboardId);
      return;
    }

    if (!modificationPrompt || !modificationPrompt.trim()) {
      setError("Please enter a modification prompt.");
      return;
    }

    setIsLoading(true);
    setError("");

    try {
      console.log(`🛠 Modifying dashboard ${dashboardId} with prompt:`, modificationPrompt);
      const url = new URL(`${API_BASE_URL}/modify/${dashboardId}`);
      url.searchParams.set("modification_prompt", modificationPrompt);
      url.searchParams.set("allow_undo", "true");

      const res = await fetch(url.toString(), { method: "POST" });
      if (!res.ok) throw new Error(`Modify failed: ${res.status}`);

      const json = await res.json();
      let updatedContent;

      // Safely parse returned content
      if (typeof json.content === "string") {
        try {
          updatedContent = JSON.parse(json.content);
        } catch {
          updatedContent = { overview: json.content };
        }
      } else {
        updatedContent = json.content;
      }

      updatedContent.dashboard_id = dashboardId;

      // Save history for undo
      setDashboardHistory((prev) => [
        { index, oldContent: dashboards[index], dashboardId },
        ...prev,
      ]);

      // Replace old dashboard
      setDashboards((prev) => {
        const copy = [...prev];
        copy[index] = updatedContent;
        return copy;
      });

      setSelectedDashboardContent(updatedContent);
      setActiveTab("overview");
      setIsInitialView(false);

      console.log("✅ Dashboard modified successfully:", updatedContent);
    } catch (err) {
      console.error("❌ Modify dashboard error:", err);
      setError(err.message || "Modify failed");
    } finally {
      setIsLoading(false);
    }
  };

  // 4) Undo (will use last item in dashboardHistory). If you want server-side undo, call POST /dashboard/undo/{dashboardId}
  const handleUndo = async () => {
    if (dashboardHistory.length === 0) return;
    const [last, ...rest] = dashboardHistory;
    setDashboardHistory(rest);

    // Option A: undo locally
    setDashboards(prev => {
      const copy = [...prev];
      copy[last.index] = last.oldContent;
      return copy;
    });
    if (selectedDashboardIndex === last.index) setSelectedDashboardContent(last.oldContent);

    // Option B (server-side): call /dashboard/undo/{dashboardId} to restore DB and then fetch content
    // try {
    //   const res = await fetch(`${API_BASE_URL}/dashboard/undo/${last.dashboardId}`, { method: 'POST' });
    //   if (res.ok) {
    //     const json = await res.json();
    //     const restored = await fetchDashboardContentById(last.dashboardId);
    //     // replace content with restored
    //   }
    // } catch (err) { console.warn('Server-side undo failed, falling back to local undo', err); }
  };
  
   const handleGenerate = async () => {
  setIsLoading(true);
  setError('');

  try {
    // Determine dashboard content robustly
    const dashboardContent =
      expandedDashboard?.type === 'prompt'
        ? promptDashboard
        : expandedDashboard?.type === 'content' && typeof expandedDashboard?.index === 'number'
        ? dashboards[expandedDashboard.index]
        : selectedDashboardContent || promptDashboard || (dashboards && dashboards[selectedDashboardIndex]);

    if (!dashboardContent) {
      const msg = 'No dashboard content available. Please select or generate one first.';
      console.warn(msg);
      setError(msg);
      toast.warn(msg);
      setIsLoading(false);
      return;
    }

    // Make sure QA tab is visible
    if (activeTab !== 'qa') setActiveTab('qa');

    // Sync dashboard content
    if (!selectedDashboardContent) {
      setSelectedDashboardContent(dashboardContent);
    }

    const difficultyLevel = qaGenerationSettings?.difficulty || difficulty || 'medium';
    const numQuestions = sliderValue || qaGenerationSettings?.numQuestions || 5;

    console.log("Sending to backend:", {
      dashboardContent,
      num_qa: numQuestions,
      difficulty: difficultyLevel
    });

    const formData = new FormData();
    formData.append('dashboard_content', dashboardContent);
    formData.append('num_qa', numQuestions);
    formData.append('difficulty', difficultyLevel);

    const response = await fetch(`${API_BASE_URL}/generate-QA`, {
      method: 'POST',
      body: formData,
    });

    console.log("Raw response object:", response);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    console.log("Parsed JSON data from backend:", data);

    let returned = [];

    // Handle structured response (array of QAs)
    if (Array.isArray(data.content)) {
      returned = data.content;
    } 
    // Handle formatted QA array
    else if (Array.isArray(data.formatted_qa)) {
      returned = data.formatted_qa;
    } 
    // Handle text-based QA (line-by-line fallback)
    else if (typeof data.content === 'string') {
      const lines = data.content.split('\n').filter((line) => line.trim());
      for (let i = 0; i < lines.length; i += 2) {
        if (
          lines[i].startsWith('Q') &&
          i + 1 < lines.length &&
          lines[i + 1].startsWith('A')
        ) {
          const questionText = lines[i].substring(lines[i].indexOf(':') + 1).trim();
          const answerText = lines[i + 1].substring(lines[i + 1].indexOf(':') + 1).trim();

          returned.push({
            question: questionText,
            answer: answerText,
          });
        }
      }
    }

    // Limit results
    const limited = returned.slice(0, numQuestions);

    // Standardize structure for frontend
    const formattedQuestions = limited.map((qa, index) => ({
      id: index + 1,
      type: 'general',
      text: qa.question || qa[0] || '',
      status: 'unanswered',
      answer: [qa.answer || qa[1] || ''],
      difficulty: difficultyLevel,
    }));

    console.log("Final formatted questions:", formattedQuestions);

    setDisplayedQuestions(formattedQuestions);
    setExpandedQuestions(new Set());
    toast.success(`Generated ${formattedQuestions.length} new questions!`);
  } catch (error) {
    console.error('Error generating questions:', error);
    setError(`Failed to generate questions: ${error.message}`);
    toast.error(`Failed to generate questions: ${error.message}`);
  } finally {
    setIsLoading(false);
  }
};
   
  // Define the handler outside JSX
  const handleDashboardClick = (content) => {
    if (!content) {
      console.log("➕ No dashboard clicked — nothing selected");
      return;
    }
    console.log("Clicked dashboard content:", content);

    if (selectedDashboardId === content.dashboard_id) {
      console.log("➖ Dashboard was already selected — now unselecting it");
      // Unselect
      setSelectedDashboardId(null);
      setSelectedDashboardIndex(null);
      setSelectedDashboardContent(null);
      setActiveTab(null);

      // Reset QA state when deselecting
      setSliderValue(10);
      setDisplayedQuestions([]);
    } else {
      console.log("✅ Selecting dashboard with ID:", content.dashboard_id);
      // Select
      setSelectedDashboardId(content.dashboard_id);
      const index = dashboards.findIndex(d => d.dashboard_id === content.dashboard_id);
      setSelectedDashboardIndex(index);
      setSelectedDashboardContent(content);
      setActiveTab('overview');

        // Reset QA state when switching to new dashboard
      setSliderValue(10);
      setDisplayedQuestions([]);
    }
  };

  const handleDelete = async () => {
    if (!selectedDashboardId) {
      console.warn("No dashboard selected to delete");
      return;
    }

    try {
      const url = new URL(`${API_BASE_URL}/delete/${selectedDashboardId}`);
      const res = await fetch(url, {
        method: "DELETE",
      });

      if (!res.ok) {
        throw new Error(`Failed to delete dashboard ${selectedDashboardId}`);
      }

      console.log(`✅ Dashboard ${selectedDashboardId} deleted successfully`);

      // Optional: update local state to remove deleted dashboard
      setDashboards(prev => prev.filter(d => d.dashboard_id !== selectedDashboardId));
      setSelectedDashboardId(null);
      setSelectedDashboardContent(null);

    } catch (error) {
      console.error("Error deleting dashboard:", error);
    }
  };
  
  /* ---------------------- QA Components ---------------------- */
 const QAGenerationSettings = () => (<div /> /* Placeholder for settings UI */);
  const QuestionPanel = React.memo(({ questions }) => {
    const handleToggleQuestion = React.useCallback((questionId) => {
      setExpandedQuestions(prev => {
        const newSet = new Set(prev);
        if (newSet.has(questionId)) {
          newSet.delete(questionId);
        } else {
          newSet.add(questionId);
        }
        return newSet;
      });
    }, []);

    

    return (
      <div className="">
        {/* Add QA Generation Settings */}
        <QAGenerationSettings />
        {questions.length > 0 ? (
          <div className="mt-4">
            {questions.map((question) => (
              <Question
                key={`question-${question.id}`}
                question={question}
                isExpanded={expandedQuestions.has(question.id)}
                onToggle={handleToggleQuestion}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-12 w-12 mx-auto text-gray-400 mb-3"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <p>No questions generated yet. Click the GENERATE Q&A button to create questions.</p>
          </div>
        )}
      </div>
    );
  });

// Also ensure the parent component is properly memoized

    const handleToggleQuestion = React.useCallback((questionId) => {
      setExpandedQuestions(prev => {
        const newSet = new Set(prev);
        if (newSet.has(questionId)) {
          newSet.delete(questionId);
        } else {
          newSet.add(questionId);
        }
        return newSet;
      });
    }, []);
  
  const handleFollowUpClick = async () => {
  if (!displayedQuestions || displayedQuestions.length === 0) {
    toast.warn('No generated questions available to create follow-ups');
    return;
  }

  setIsGeneratingQA(true);
  setError('');
  try {
    // Combine ALL existing Q&A pairs into one text block
    const qaText = displayedQuestions
      .map((q, i) => {
        const question = q.text || q.question || '';
        const answer = q.answer?.[0] || q.answer || '';
        return `Q${i + 1}: ${question}\nA${i + 1}: ${answer}`;
      })
      .join('\n\n');

    const followUpPrompt = `Generate follow-up questions based on the following Q&A pairs:\n${qaText}`;

    const seed = Math.random().toString(36).slice(2);
    const timestamp = Date.now();

    const formData = new FormData();
    formData.append('dashboard_content', followUpPrompt);
    formData.append('num_qa', sliderValue);
    formData.append('difficulty', qaGenerationSettings.difficulty || 'medium');
    formData.append('seed', seed);
    formData.append('timestamp', String(timestamp));

    // Clear previous follow-ups immediately
    setFollowUpQuestions([]);

    const response = await fetch(`${API_BASE_URL}/generate-QA`, {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP error! status: ${response.status}`);
    }

    const data = await response.json();

    let returned = [];
    if (Array.isArray(data.content)) {
      returned = data.content;
    } else if (typeof data.content === 'string') {
      returned = parseQAContent(data.content);
    } else if (Array.isArray(data.formatted_qa)) {
      returned = data.formatted_qa;
    }

    const requested = sliderValue || qaGenerationSettings?.numQuestions || 5;
    const limited = returned.slice(0, requested);

    const appended = limited.map((qa, idx) => {
      const id = Number(`${Date.now()}${idx}`);
      return {
        id,
        type: 'followup',
        text: qa.question || qa[0] || (typeof qa === 'string' ? qa : ''),
        status: 'unanswered',
        answer: [qa.answer || qa[1] || ''],
      };
    });

    setFollowUpQuestions(appended);
    setExpandedQuestions(prev => {
      const next = new Set(prev);
      appended.forEach(q => next.add(q.id));
      return next;
    });

    toast.success(`Added ${appended.length} follow-up questions`);
  } catch (error) {
    console.error('Error generating follow-up questions:', error);
    setError(`Failed to generate follow-ups: ${error.message}`);
    toast.error(`Failed to generate follow-ups: ${error.message}`);
  } finally {
    setIsGeneratingQA(false);
  }
};

  // Generate follow-ups based on words selected by the user in an answer
  const handleGenerateFromSelection = async (parentQuestion) => {
    try {
      const selectedText = (window.getSelection && window.getSelection().toString && window.getSelection().toString()) || '';
      if (!selectedText || !selectedText.trim()) {
        toast.warn('Please select 2-3 words in an answer to generate follow-ups');
        return;
      }

      // Extract words and sanitize
      const words = selectedText.trim().split(/\s+/).map(w => w.replace(/[.,!?;:\\()\[\]"']/g, '')).filter(Boolean);
      if (words.length === 0) {
        toast.warn('No valid words selected');
        return;
      }

      // Prefer 2-3 words as guidance; if more than 3 selected, take the first 3
      const selectedWords = words.length > 3 ? words.slice(0, 3) : words;
      if (selectedWords.length < 1) {
        toast.warn('Select 1-3 meaningful words from the answer');
        return;
      }

      setIsGeneratingQA(true);
      setError('');

      // Build a compact context (question + answer) to send as dashboard_content
      const answerText = Array.isArray(parentQuestion.answer) ? parentQuestion.answer.join('\n') : (parentQuestion.answer || '');
      const dashboardContext = `Question: ${parentQuestion.text}\nAnswer: ${answerText}`;

      const formData = new FormData();
      formData.append('dashboard_content', dashboardContext);
      formData.append('num_qa', String(sliderValue || qaGenerationSettings.numQuestions || 5));
      formData.append('difficulty', qaGenerationSettings.difficulty || difficulty || 'medium');
      formData.append('selected_words', selectedWords.join(','));

      const response = await fetch(`${API_BASE_URL}/generate-QA`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const txt = await response.text();
        throw new Error(`HTTP ${response.status}: ${txt}`);
      }

      const data = await response.json();
      const qaContent = data.content || data.qa_pairs || '';
      const parsed = parseQAContent(typeof qaContent === 'string' ? qaContent : JSON.stringify(qaContent));

      const requested = Number(sliderValue || qaGenerationSettings.numQuestions || 5);
      const limited = parsed.slice(0, requested);

      const appended = limited.map((qa, idx) => ({
        id: `${parentQuestion.id}-followup-${Date.now()}-${idx}`,
        text: qa.question || qa.q || qa.question_text || qa.question || '',
        answer: qa.answer || qa.a || qa.answer_text || '',
        type: 'followup',
        parentId: parentQuestion.id,
      }));

      // Store follow-ups per parent question
      setNestedFollowUps(prev => ({
        ...prev,
        [parentQuestion.id]: appended
      }));

      // Auto-expand the new follow-up questions
      setExpandedQuestions(prev => {
        const next = new Set(prev);
        appended.forEach(q => next.add(q.id));
        return next;
      });

      toast.success(`Generated ${appended.length} follow-up questions based on selection`);
    } catch (err) {
      console.error('Error generating from selection:', err);
      toast.error(`Failed to generate follow-ups: ${err.message}`);
      setError(err.message || String(err));
    } finally {
      setIsGeneratingQA(false);
    }
  };
  
  const QA_COLORS = [
    { border: 'border-blue-500', bg: 'bg-blue-50', text: 'text-blue-800' },
    { border: 'border-purple-500', bg: 'bg-purple-50', text: 'text-purple-800' },
    { border: 'border-green-500', bg: 'bg-green-50', text: 'text-green-800' },
    { border: 'border-amber-500', bg: 'bg-amber-50', text: 'text-amber-800' },
    { border: 'border-rose-500', bg: 'bg-rose-50', text: 'text-rose-800' },
  ];
  // Replace the Question component with this implementation
  const Question = React.memo(({ question, isExpanded, onToggle }) => {
    // Compute a stable color index even when question.id is a string
    let colorIndex = 0;
    try {
      if (typeof question.id === 'number' && !isNaN(question.id)) {
        colorIndex = Math.abs(question.id) % QA_COLORS.length;
      } else if (typeof question.id === 'string') {
        // Try to extract a trailing number (e.g., followup-162738) first
        const match = question.id.match(/(\d+)$/);
        if (match) {
          colorIndex = Math.abs(Number(match[1])) % QA_COLORS.length;
        } else {
          // Fallback: compute a simple hash of the string
          let h = 0;
          for (let i = 0; i < question.id.length; i++) {
            h = (h << 5) - h + question.id.charCodeAt(i); // h * 31 + char
            h |= 0; // force 32bit int
          }
          colorIndex = Math.abs(h) % QA_COLORS.length;
        }
      } else {
        colorIndex = 0;
      }
    } catch (err) {
      colorIndex = 0;
    }

    const colorSet = QA_COLORS[colorIndex] || QA_COLORS[0];
     const [openFollowUps, setOpenFollowUps] = useState(false);
    const handleToggle = React.useCallback((e) => {
      e.stopPropagation();
      e.preventDefault();
      onToggle(question.id);
    }, [question.id, onToggle]);

    const [collapsedFollowUpSections, setCollapsedFollowUpSections] = useState(new Set());

    const handleToggleFollowUpSection = React.useCallback((parentQuestionId) => {
    setCollapsedFollowUpSections(prev => {
      const newSet = new Set(prev);
      if (newSet.has(parentQuestionId)) {
        newSet.delete(parentQuestionId);
      } else {
        newSet.add(parentQuestionId);
      }
      return newSet;
    });
  }, []);
    return (
      <div className="mb-4 border-b border-gray-200 pb-4 hover:bg-gray-50 transition duration-200 rounded-lg">
        <div className={`pl-4 py-3 ${colorSet.bg} rounded-md border-l-4 ${colorSet.border} shadow-sm mb-2`}>
          <div className="flex items-center justify-between">
            <span className={`font-semibold ${colorSet.text}`}>{question.text}</span>
            <button
              onClick={handleToggle}
              className="ml-4 p-2 text-indigo-600 hover:text-indigo-800 hover:bg-indigo-50 rounded-full focus:outline-none"
              type="button"
              aria-label={isExpanded ? "Hide answer" : "Show answer"}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d={isExpanded
                    ? "M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z"
                    : "M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                  }
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        </div>

        {isExpanded && (
          <div className={`pl-4 py-3 ${colorSet.bg} rounded-md border-l-4 ${colorSet.border} shadow-sm`}>
            {question.answer ? (
              Array.isArray(question.answer) ? (
                <ul className="list-none pl-0 space-y-1">
                  {question.answer.map((ans, index) => (
                    <li key={index} className={colorSet.text}>
                      {ans}
                    </li>
                  ))}
                </ul>
              ) : (
                <div>
                  <p className={colorSet.text}>{question.answer}</p>
                </div>
              )
            ) : (
              <p className="text-gray-500 italic">No answer available.</p>
            )}

            {/* Button to generate follow-ups based on selected words in the answer (for ALL QAs) */}
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleGenerateFromSelection(question)}
                className="px-3 py-1 text-sm bg-amber-500 text-white rounded-md hover:bg-amber-600"
              >
                Generate from selection
              </button>
              <span className="text-xs text-gray-500">Select 1-3 words in the answer and click the button</span>
            </div>

            {/* Display nested follow-up questions */}
            {/* {nestedFollowUps[question.id] && nestedFollowUps[question.id].length > 0 && (
              <div className="mt-4 ml-4 space-y-3 border-l-2 border-gray-300 pl-4">
                <div className="text-sm font-medium text-gray-600 mb-2">Follow-up Questions:</div>
                {nestedFollowUps[question.id].map((followUpQ) => (
                  <NestedQuestion
                    key={followUpQ.id}
                    question={followUpQ}
                    isExpanded={expandedQuestions.has(followUpQ.id)}
                    onToggle={handleToggleQuestion}
                    onGenerateFromSelection={handleGenerateFromSelection}
                  />
                ))}
              </div>
            )}         */}
            {/* Display nested follow-up questions */}
            {nestedFollowUps[question.id] && nestedFollowUps[question.id].length > 0 && (
              <div className="mt-4 ml-4 space-y-3 border-l-2 border-gray-300 pl-4">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium text-gray-600">Follow-up Questions:</div>
                  <button
                    type="button"
                    onClick={() => handleToggleFollowUpSection(question.id)}
                    className="p-1 text-gray-600 hover:text-gray-800 hover:bg-gray-200 rounded-full focus:outline-none"
                    aria-label={collapsedFollowUpSections.has(question.id) ? "Expand follow-up questions" : "Collapse follow-up questions"}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      className="h-4 w-4"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path
                        fillRule="evenodd"
                        d={!collapsedFollowUpSections.has(question.id)
                          ? "M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z"
                          : "M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                        }
                        clipRule="evenodd"
                      />
                    </svg>
                  </button>
                </div>
                
                {!collapsedFollowUpSections.has(question.id) && (
                  <div>
                    {nestedFollowUps[question.id].map((followUpQ) => (
                      <NestedQuestion
                        key={followUpQ.id}
                        question={followUpQ}
                        isExpanded={expandedQuestions.has(followUpQ.id)}
                        onToggle={handleToggleQuestion}
                        onGenerateFromSelection={handleGenerateFromSelection}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  });

  // NestedQuestion component for follow-up questions
  const NestedQuestion = React.memo(({ question, isExpanded, onToggle, onGenerateFromSelection }) => {
    const colorSet = { border: 'border-amber-500', bg: 'bg-amber-50', text: 'text-amber-800' };

    const [collapsedFollowUpSections, setCollapsedFollowUpSections] = useState(new Set());

    const handleToggleFollowUpSection = React.useCallback((parentQuestionId) => {
      setCollapsedFollowUpSections(prev => {
        const newSet = new Set(prev);
        if (newSet.has(parentQuestionId)) {
          newSet.delete(parentQuestionId);
        } else {
          newSet.add(parentQuestionId);
        }
        return newSet;
      });
    }, []);

    const handleToggle = React.useCallback((e) => {
      e.stopPropagation();
      e.preventDefault();
      onToggle(question.id);
    }, [question.id, onToggle]);

    return (
      <div className="mb-3 border border-gray-200 rounded-lg hover:bg-gray-50 transition duration-200">
        <div className={`pl-3 py-2 ${colorSet.bg} rounded-t-lg border-l-4 ${colorSet.border}`}>
          <div className="flex items-center justify-between">
            <span className={`text-sm font-medium ${colorSet.text}`}>{question.text}</span>
            <button
              onClick={handleToggle}
              className="ml-2 p-1 text-amber-600 hover:text-amber-800 hover:bg-amber-100 rounded-full focus:outline-none"
              type="button"
              aria-label={isExpanded ? "Hide answer" : "Show answer"}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-4 w-4"
                viewBox="0 0 20 20"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d={isExpanded
                    ? "M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z"
                    : "M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                  }
                  clipRule="evenodd"
                />
              </svg>
            </button>
          </div>
        </div>

        {isExpanded && (
          <div className={`pl-3 py-2 ${colorSet.bg} rounded-b-lg border-l-4 ${colorSet.border}`}>
            {question.answer ? (
              Array.isArray(question.answer) ? (
                <ul className="list-none pl-0 space-y-1">
                  {question.answer.map((ans, index) => (
                    <li key={index} className={`text-sm ${colorSet.text}`}>
                      {ans}
                    </li>
                  ))}
                </ul>
              ) : (
                <div>
                  <p className={`text-sm ${colorSet.text}`}>{question.answer}</p>
                </div>
              )
            ) : (
              <p className="text-gray-500 italic text-sm">No answer available.</p>
            )}

            {/* Button to generate follow-ups based on selected words in the answer */}
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                onClick={() => onGenerateFromSelection(question)}
                className="px-2 py-1 text-xs bg-amber-500 text-white rounded hover:bg-amber-600"
              >
                Generate from selection
              </button>
              <span className="text-xs text-gray-500">Select 1-3 words and click</span>
            </div>

            {/* Display nested follow-ups for follow-up questions */}
            {/* {nestedFollowUps[question.id] && nestedFollowUps[question.id].length > 0 && (
              <div className="mt-3 ml-3 space-y-2 border-l-2 border-gray-300 pl-3">
                <div className="text-xs font-medium text-gray-600 mb-1">Follow-up Questions:</div>
                {nestedFollowUps[question.id].map((followUpQ) => (
                  <NestedQuestion
                    key={followUpQ.id}
                    question={followUpQ}
                    isExpanded={expandedQuestions.has(followUpQ.id)}
                    onToggle={onToggle}
                    onGenerateFromSelection={onGenerateFromSelection}
                  />
                ))}
              </div>
            )} */}
            {/* Display nested follow-ups for follow-up questions */}
          {nestedFollowUps[question.id] && nestedFollowUps[question.id].length > 0 && (
            <div className="mt-3 ml-3 space-y-2 border-l-2 border-gray-300 pl-3">
              <div className="flex items-center justify-between">
                <div className="text-xs font-medium text-gray-600">Follow-up Questions:</div>
                <button
                  type="button"
                  onClick={() => handleToggleFollowUpSection(question.id)}
                  className="p-1 text-gray-600 hover:text-gray-800 hover:bg-gray-200 rounded-full focus:outline-none"
                  aria-label={collapsedFollowUpSections.has(question.id) ? "Expand follow-up questions" : "Collapse follow-up questions"}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    className="h-3 w-3"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d={!collapsedFollowUpSections.has(question.id)
                        ? "M14.707 12.707a1 1 0 01-1.414 0L10 9.414l-3.293 3.293a1 1 0 01-1.414-1.414l4-4a1 1 0 011.414 0l4 4a1 1 0 010 1.414z"
                        : "M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
                      }
                      clipRule="evenodd"
                    />
                  </svg>
                </button>
              </div>
              
              {!collapsedFollowUpSections.has(question.id) && (
                <div>
                  {nestedFollowUps[question.id].map((followUpQ) => (
                    <NestedQuestion
                      key={followUpQ.id}
                      question={followUpQ}
                      isExpanded={expandedQuestions.has(followUpQ.id)}
                      onToggle={onToggle}
                      onGenerateFromSelection={onGenerateFromSelection}
                    />
                  ))}
                </div>
              )}
            </div>
          )}
          </div>
        )}
      </div>
    );
  });

  // console.log("Dashboard IDs:", dashboards.map(d => d.dashboard_id));
  /* ---------------------- UI ---------------------- */
 return (
   <>
      <style>{`
        .hide-scrollbar::-webkit-scrollbar {
          display: none; /* Chrome, Safari, Edge */
        }
        .hide-scrollbar {
          -ms-overflow-style: none;  /* IE 10+ */
          scrollbar-width: none;      /* Firefox */
        }
      `}</style>
      <div className="min-h-screen bg-gray-100">
        <div className={`bg-white shadow-xl transition-all duration-300 overflow-y-auto border-l`}> {/* Removed isHovered for simplicity */}      
          <div className="px-3 py-2 border-b border-gray-200"> {/* Header placeholder */} </div>
          {!isInitialView && dashboards.length > 0 &&(
            <div className="w-full">
              {/* Dashboard List */}
                <div className="overflow-x-auto hide-scrollbar">
                  <div className="inline-flex gap-2 px-2 py-1">
                    {dashboards.map((content,dashboardIndex) => (
                      <div                        
                        key={content.dashboard_id != null ? content.dashboard_id : `fallback-${dashboardIndex}`}                  
                        onClick={() => handleDashboardClick(content)}
                        className={`inline-block min-w-[100px] rounded-lg shadow-md transition-shadow cursor-pointer${
                        selectedDashboardId === content.dashboard_id ?  'bg-blue-50' : ''
                        } ${
                        dashboardIndex === 0 ? 'text-blue-600' :
                        dashboardIndex === 1 ? 'text-green-600' :
                        dashboardIndex === 2 ? 'text-purple-600' :
                        dashboardIndex === 3 ? 'text-red-600' :
                        dashboardIndex === 4 ? 'text-yellow-600' :
                        'text-indigo-600'
                      }`}
                      >
                        <h5
                          className={`text-xs font-medium px-4 py-2 truncate w-full text-center`}
                          title={content.dashboard_title || `Dashboard ${dashboardIndex + 1}`}
                        >
                          {content.dashboard_title || `Dashboard ${dashboardIndex + 1}`}
                        </h5>
                      </div>
                    ))}
                  </div>
                </div>

              {/* Single Tab Navigation */}
              {selectedDashboardIndex !== null && (
                <>
                  <div className="border-b border-gray-200 mb-4 mt-4 flex items-center justify-between">
                    <nav className="-mb-px flex space-x-8  whitespace-nowrap grow">
                      <button onClick={() => setActiveTab('overview')} className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'overview' ? 'border-indigo-500 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                        Overview
                      </button>
                      <button onClick={() => setActiveTab('qa')} className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'qa' ? 'border-indigo-500 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'}`}>
                        Q&A
                      </button>
                    </nav>
                  {/* Bin/Delete button aligned left of Undo */}                
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={!selectedDashboardId}
                      className={`mr-2 p-2 rounded text-sm flex items-center justify-center ${
                        !selectedDashboardId
                          ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                          : 'bg-blue-500 text-white hover:bg-red-600'
                      }`}
                      title="Delete Dashboard"
                    >
                      <Trash className="h-5 w-5" />
                    </button>
                  {/* Undo aligned right */}
                    <button
                      type="button"
                      onClick={handleUndo}
                      disabled={dashboardHistory.length === 0}
                      className={`ml-auto px-3 py-1 rounded text-sm ${
                        dashboardHistory.length === 0
                          ? "bg-gray-300 text-gray-500 cursor-not-allowed"
                          : "bg-yellow-500 text-white hover:bg-yellow-600"
                      }`}
                    >
                      Undo
                    </button>
                  </div>

                  {/* Tab Content */}
                  <div className="bg-white rounded-lg shadow-md">
                    {activeTab === 'overview' && selectedDashboardContent && (
                      <div className="px-6 pb-6">
                        <div className="flex justify-between gap-6 items-start">
                          <div className="w-1/3 self-start pt-0 ">
                            <div className="space-y-2">
                              {Array.isArray(selectedDashboardContent.overview)&& selectedDashboardContent.overview.length > 0 ? (
                                  selectedDashboardContent.overview.map((line, index) => (
                                    <div key={index} className="flex items-start space-x-2">
                                      <span className="text-indigo-500">•</span>
                                      <p className="text-sm text-gray-700">{line}</p>
                                    </div>
                                  ))
                                ) : (
                                <p className="text-gray-500 italic">No overview available</p>
                              )}
                            </div>
                          </div>
                          <div className="w-2/3 flex justify-center items-center min-h-[450px] bg-gray-50 rounded-lg">
                            <DashboardChart content={Array.isArray(selectedDashboardContent.overview)
                                  ? selectedDashboardContent.overview.join('\n')
                                  : selectedDashboardContent.overview || ''
                            } type={['pie', 'donut', 'bar', 'line', 'area', 'radar'][selectedDashboardIndex % 6]} />
                          </div>
                        </div>
                      </div>
                    )}

                    {activeTab === 'qa' && (
                      <div className="p-6">
                        <div className="bg-white shadow-lg rounded-lg">

                          {/* AI Generate Side */}
                            <div>
                              <div className="flex p-4 bg-indigo-50 border-b border-gray-200">
                                <div className="w-12 h-8 bg-indigo-600 rounded-full flex items-center justify-center text-white mr-4 font-medium">AI</div>
                                <h3 className="font-semibold text-gray-800">AI Generate</h3>
                                <select
                                    id="difficulty"
                                    value={difficulty}
                                    onChange={(e) => setDifficulty(e.target.value)}
                                    className="border border-gray-300 rounded-md p-1 text-sm"
                                >
                                    <option value="beginner">Beginner</option>
                                    <option value="intermediate">Intermediate</option>
                                    <option value="advanced">Advanced</option>
                                </select>
                                <input type="range" min="1" max="10" value={sliderValue} onChange={(e) => setSliderValue(Number(e.target.value))} className="w-64 accent-indigo-600" />
                                <span className="text-gray-600 font-medium">{sliderValue}</span>
                                <button onClick={handleGenerate} disabled={isLoading} className="px-3 py-2 min-w-[150px] bg-indigo-600 text-white text-xs rounded-lg hover:bg-indigo-700 focus:outline-none focus:ring-1 focus:ring-indigo-500 focus:ring-opacity-50 disabled:opacity-50 transition duration-200 text-center">
                                  {isLoading ? 'GENERATING...' : 'GENERATE QA'}
                                </button>
                              </div>

                              
                              <div className="max-h-96 overflow-y-auto">
                                <QuestionPanel questions={displayedQuestions} />
                              </div>
                            </div>
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* Message when no dashboard is selected */}
              {selectedDashboardIndex === null && (
                <div className="text-center py-8 text-gray-500 bg-white rounded-lg shadow-md">
                  <p>Select a dashboard from the list above to view its content or generate Q&A.</p>
                </div>
              )}
            </div>
          )}

          {(isInitialView) && (
            <div className="bg-white rounded-lg p-6 shadow-md">
              <div className="mb-4">
                <h3 className="text-lg font-medium text-gray-800 mb-2">Raw job description Content</h3>
                <p className="text-sm text-gray-600 mb-4">This is the original job description content. Click "Create Dashboard" in the sidebar to generate an AI-processed analysis.</p>
                <div className="bg-gray-50 p-4 rounded-lg border border-gray-200">
                    {console.log("💡 Render check - analysisData:", analysisData)}
                  {analysisData && (analysisData.content || analysisData.file?.content) ? (
                    <div className="max-h-[500px] overflow-y-auto hide-scrollbar">
                      <pre className="text-sm whitespace-pre-wrap text-gray-700">{analysisData.content || analysisData.file?.content}</pre>
                    </div>
                  ) : (
                     <div>
                      <p className="text-gray-500 italic">No job description content available</p>
                      {console.log("💡 selectedFile exists but analysisData missing:", selectedFile)}
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-6 bg-indigo-50 p-4 rounded-lg border border-indigo-200">
                <div className="flex items-start">
                  <div className="shrink-0 mt-1">
                    <svg className="h-5 w-5 text-indigo-600" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2h-1V9z" clipRule="evenodd"></path></svg>
                  </div>
                  <div className="ml-3">
                    <h3 className="text-sm font-medium text-indigo-800">How to use this tool</h3>
                    <div className="mt-2 text-sm text-indigo-700">
                      <ul className="list-disc pl-5 space-y-1">
                        <li>Use the left sidebar to set up your dashboard options.</li>
                        <li>Move the "Number of Dashboards" slider to choose how many versions to create.</li>
                        <li>Click "Create Dashboard" to generate dashboards with AI analysis.</li>
                        <li>The prompt box shows "Modify Selected Dashboard" if a dashboard is open, or "Create Dashboard" if none is selected.</li>
                        <li>Click a Dashboard tab title to select and modify an existing dashboard.</li>
                        <li>To generate a dashboard with a custom prompt, click the title of the open dashboard tab to deselect it.</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {error && (
            <div className="mt-4 p-4 bg-red-50 text-red-700 rounded-lg border border-red-200">
              <p>{error}</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
};

Dashboard.propTypes = {
  analysisData: PropTypes.object,
  hasGeneratedDashboard: PropTypes.bool,
  selectedDashboardId: PropTypes.string,
  setSelectedDashboardId: PropTypes.func,
};
