// components/rightsidebar/index.jsx
"use client";
import React, { useEffect, useRef, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import Dashboards from './Dashboards.jsx';
import VideoSession from './videoSession.jsx';
import SessionManager from './SessionManager.jsx';

import { useRecording } from './useRecording.jsx';
import { Mic, StopCircle, Copy, ExternalLink, MicOff, VideoOff, Video, Settings } from 'lucide-react';

// Removed Socket.IO import - using native WebSocket instead

export default function RightSidebar({ analysisData, hasGeneratedDashboard,selectedDashboardId,setSelectedDashboardId,selectedFile }) {
  const processedRef = useRef(false);
  const sessionIdRef = useRef(''); // Add ref to track sessionId
  const [processedData, setProcessedData] = useState(null);
  const [candidateName, setCandidateName] = useState('Unknown Candidate');
  const [interviewerName, setInterviewerName] = useState('Interviewer');
  
  // Enhanced session management with comprehensive ID tracking
  const [sessionMetadata, setSessionMetadata] = useState({
    sessionId: '',
    resumeId: '',
    jdId: '',
    interviewerId: '',
    candidateId: '',
    organizationId: '',
    sessionStartTime: null,
    sessionDuration: 3600, // 1 hour in seconds
    maxDuration: 3600000, // 1 hour in milliseconds
    participants: []
  });
  const [qaHistory, setQaHistory] = useState([]);
  const [score, setScore] = useState({ correct: 0, total: 0 });
  const [localError, setLocalError] = useState('');
  const [isInitializing, setIsInitializing] = useState(false);
  const [sessionLink, setSessionLink] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [showSessionLink, setShowSessionLink] = useState(false);
  const [copied, setCopied] = useState(false);
  const [isGeneratingSession, setIsGeneratingSession] = useState(false);
  const [showVideoSection, setShowVideoSection] = useState(false);
  
  // New state variables for mic/cam status and alerts
  const [isMicOn, setIsMicOn] = useState(true);
  const [isCamOn, setIsCamOn] = useState(true);
  const [alerts, setAlerts] = useState(['Low eye contact detected']);
  const [showSessionManager, setShowSessionManager] = useState(false);
  const [transcriptionActivity, setTranscriptionActivity] = useState(false);

  const [mediaStream, setMediaStream] = useState(null);
  const [detectionMetrics, setDetectionMetrics] = useState({
    eyeContact: 'Average',
    speakingPace: 'Slow',
    background: 'Noisy',
    audioQuality: 'Good'
  });
  const videoRef = useRef(null);
  const remoteVideoRef = useRef(null);
  const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000';
  const {
    isRecording, recordingState, timer, audioLevel, micPermissionStatus, error: recordingHookError,
    startRecording: startRecordingHook, stopRecording: stopRecordingHook,
    onTranscriptReceivedRef, onRecordingErrorRef,
  } = useRecording();

  useEffect(() => {
    if (recordingHookError) {
      setLocalError(recordingHookError);
    } else {
      setLocalError('');
    }
  }, [recordingHookError]);

  // Video stream assignment effect
  useEffect(() => {
    if (mediaStream && videoRef.current && showVideoSection) {
      console.log('[RightSidebar] 📹 Assigning media stream to local video element');
      videoRef.current.srcObject = mediaStream;
      videoRef.current.play().catch(err => {
        console.warn('[RightSidebar] ⚠️ Autoplay failed for local video:', err);
      });
    }
  }, [mediaStream, showVideoSection]);

  const handleTranscriptReceived = useCallback((transcriptData) => {
    console.log('🎯 [TRANSCRIPT-RECEIVED] Real-time transcription arrived!');
    console.log('📝 [TRANSCRIPT-DATA]:', transcriptData);
    
    // Extract data with proper fallbacks
    const { speaker, text, timestamp, speaker_name, speaker_role } = transcriptData;
    
    console.log('📝 [TRANSCRIPT-DETAILS]:', {
      speaker,
      speaker_name, 
      speaker_role,
      textLength: text?.length || 0,
      text: text?.slice(0, 50) + '...'
    });
    
    // STRICT speaker validation - reject invalid transcripts
    let mappedSpeaker = null;
    
    // First try direct speaker field
    if (speaker && (speaker.toLowerCase().includes('interviewer') || speaker.toLowerCase().includes('candidate'))) {
      if (speaker.toLowerCase().includes('interviewer')) {
        mappedSpeaker = 'interviewer';
      } else if (speaker.toLowerCase().includes('candidate')) {
        mappedSpeaker = 'candidate';
      }
    }
    
    // Fallback to role fields only if speaker field is invalid
    if (!mappedSpeaker) {
      if (speaker_role === 'interviewer' || speaker_name === 'interviewer') {
        mappedSpeaker = 'interviewer';
      } else if (speaker_role === 'candidate' || speaker_name === 'candidate') {
        mappedSpeaker = 'candidate';
      }
    }
    
    // Reject transcript if no valid role identified
    if (!mappedSpeaker) {
      console.error('❌ [TRANSCRIPT REJECTED] Cannot identify valid speaker role:', transcriptData);
      return;
    }
    
    // STRICT text validation - reject invalid transcripts
    if (!text || typeof text !== 'string' || text.trim().length < 3) {
      console.error('❌ [TRANSCRIPT REJECTED] Empty, invalid or too short text:', text);
      return;
    }
    
    // Check for repetitive or meaningless content
    const cleanText = text.trim().toLowerCase();
    const suspiciousPatterns = ['thank you thank you', 'hello hello', 'wait wait wait', 'check check'];
    if (suspiciousPatterns.some(pattern => cleanText.includes(pattern))) {
      console.error('❌ [TRANSCRIPT REJECTED] Detected repetitive/suspicious content:', text);
      return;
    }
    
    console.log('[RightSidebar] 📝 Role mapping result:', {
      originalSpeaker: speaker,
      originalSpeakerRole: speaker_role,
      originalSpeakerName: speaker_name,
      mappedSpeaker: mappedSpeaker,
      textPreview: text?.slice(0, 50) + '...',
      textLength: text?.length
    });
    
    setQaHistory((prev) => {
      const newEntry = {
        speaker: mappedSpeaker,
        message: text.trim(),
        timestamp: timestamp ? new Date(timestamp).toISOString() : new Date().toISOString(),
        candidate: candidateName,
        interviewer: interviewerName,
        type: 'transcript',
        // Add session metadata to each transcript entry
        sessionMetadata: {
          sessionId: sessionMetadata.sessionId,
          resumeId: sessionMetadata.resumeId,
          jdId: sessionMetadata.jdId,
          interviewerId: sessionMetadata.interviewerId,
          candidateId: sessionMetadata.candidateId,
          organizationId: sessionMetadata.organizationId
        }
      };
      
      // Check if we should append to the last message from the same speaker (within 5 seconds)
      const lastEntry = prev.length > 0 ? prev[prev.length - 1] : null;
      const lastTimestamp = lastEntry ? new Date(lastEntry.timestamp).getTime() : 0;
      const currentTimestamp = new Date(newEntry.timestamp).getTime();
      const timeDiff = currentTimestamp - lastTimestamp;
      
      if (lastEntry && 
          lastEntry.speaker === mappedSpeaker && 
          timeDiff < 5000 && // Only append if within 5 seconds
          !lastEntry.message.endsWith('.') && 
          !lastEntry.message.endsWith('!') && 
          !lastEntry.message.endsWith('?')) {
        
        const updatedPrev = [...prev];
        const separator = ' '; // Use space for real-time streaming
        updatedPrev[updatedPrev.length - 1].message += `${separator}${text.trim()}`;
        updatedPrev[updatedPrev.length - 1].timestamp = newEntry.timestamp; // Update timestamp
        console.log('[RightSidebar] 📝 Real-time append:', text.trim());
        
        // Show transcription activity
        setTranscriptionActivity(true);
        setTimeout(() => setTranscriptionActivity(false), 2000);
        
        // Store complete transcript data (throttled)
        if (timeDiff > 1000) { // Only save every second to reduce overhead
          localStorage.setItem('sessionTranscript', JSON.stringify(updatedPrev));
        }
        return updatedPrev;
      } else {
        const newHistory = [...prev, newEntry];
        console.log('[RightSidebar] 📝 New transcript entry:', newEntry);
        
        // Store complete transcript data
        localStorage.setItem('sessionTranscript', JSON.stringify(newHistory));
        return newHistory;
      }
    });
  }, [candidateName, interviewerName, sessionMetadata]);

  const handleRecordingError = useCallback((message) => {
    setLocalError(message);
  }, []);

  useEffect(() => {
    onTranscriptReceivedRef.current = handleTranscriptReceived;
    onRecordingErrorRef.current = handleRecordingError;
    console.log('[RightSidebar] 🔧 Set up transcript and error handlers');
  }, [handleTranscriptReceived, handleRecordingError, onTranscriptReceivedRef, onRecordingErrorRef]);

  useEffect(() => {
    if (!analysisData) return;
    console.log('[RightSidebar] 📦 analysisData received (updating):', analysisData);
    setProcessedData(analysisData);
    const candidateNameFromData = analysisData.candidateName || analysisData.name || 'Unknown Candidate';
    setCandidateName(candidateNameFromData);
    
    // Extract IDs from analysisData and URL params
    const urlParams = new URLSearchParams(window.location.search);
    const resumeId = urlParams.get('resumeId') || analysisData.resumeId || analysisData.id || '';
    const jdId = urlParams.get('jdId') || analysisData.jdId || '';
    
    // Update session metadata with available IDs
    setSessionMetadata(prev => ({
      ...prev,
      resumeId: resumeId,
      jdId: jdId,
      candidateId: `candidate_${resumeId}_${Date.now()}`,
      participants: [{
        role: 'candidate',
        name: candidateNameFromData,
        id: `candidate_${resumeId}_${Date.now()}`,
        joinedAt: new Date().toISOString()
      }]
    }));
  }, [analysisData]);

  // Get interviewer name and ID from localStorage or context
  useEffect(() => {
    try {
      const storedUserName = localStorage.getItem('userName') || localStorage.getItem('user_name') || localStorage.getItem('interviewer_name');
      const storedUser = localStorage.getItem('user');
      const storedUserId = localStorage.getItem('userId') || localStorage.getItem('user_id');
      const storedOrgId = localStorage.getItem('organizationId') || localStorage.getItem('organization_id');
      
      let interviewerNameFromStorage = 'Interviewer';
      let interviewerIdFromStorage = `interviewer_${Date.now()}`;
      
      if (storedUserName) {
        interviewerNameFromStorage = storedUserName;
        setInterviewerName(storedUserName);
      } else if (storedUser) {
        try {
          const userObj = JSON.parse(storedUser);
          if (userObj.name) {
            interviewerNameFromStorage = userObj.name;
            setInterviewerName(userObj.name);
          } else if (userObj.username) {
            interviewerNameFromStorage = userObj.username;
            setInterviewerName(userObj.username);
          }
          if (userObj.id) {
            interviewerIdFromStorage = userObj.id;
          }
        } catch (e) {
          console.log('Could not parse stored user data');
        }
      }
      
      // Update session metadata with interviewer information
      setSessionMetadata(prev => ({
        ...prev,
        interviewerId: storedUserId || interviewerIdFromStorage,
        organizationId: storedOrgId || 'default_org',
        participants: [...prev.participants, {
          role: 'interviewer',
          name: interviewerNameFromStorage,
          id: storedUserId || interviewerIdFromStorage,
          joinedAt: new Date().toISOString()
        }]
      }));
    } catch (error) {
      console.log('Error getting interviewer data from localStorage:', error);
    }
  }, []);

  // Debug useEffect to monitor sessionId changes
  useEffect(() => {
    console.log('[RightSidebar] sessionId changed:', sessionId);
  }, [sessionId]);

  // Comprehensive debug useEffect to monitor all relevant state changes
  useEffect(() => {
    console.log('[RightSidebar] State Update:', {
      sessionId,
      sessionLink,
      showSessionLink,
      showVideoSection,
      isGeneratingSession
    });
  }, [sessionId, sessionLink, showSessionLink, showVideoSection, isGeneratingSession]);

  // Auto-extract sessionId from sessionLink when it's generated
  useEffect(() => {
    if (sessionLink && !sessionId) {
      try {
        const urlParams = new URLSearchParams(sessionLink.split('?')[1]);
        const extractedSessionId = urlParams.get('session_id');
        if (extractedSessionId) {
          console.log('[RightSidebar] Auto-extracting sessionId from sessionLink:', extractedSessionId);
          setSessionId(extractedSessionId);
          sessionIdRef.current = extractedSessionId; // Update ref immediately
          console.log('[RightSidebar] sessionId set by auto-extract to:', extractedSessionId);
        }
      } catch (error) {
        console.error('[RightSidebar] Error extracting sessionId from sessionLink:', error);
      }
    }
  }, [sessionLink, sessionId]);

  const generateSessionLink = useCallback(async () => {
    if (isGeneratingSession) return;

    setIsGeneratingSession(true);
    setLocalError('');
    
    // CRITICAL FIX: Clear any existing session state before generating new one
    console.log('[RightSidebar] Clearing existing session state before generating new session');
    setSessionId('');
    sessionIdRef.current = '';
    setShowVideoSection(false);

    console.log('[RightSidebar] Generating session link for candidate:', candidateName);

    try {
      // Create comprehensive session data with all IDs and metadata
      const sessionData = {
        role: 'recruiter',
        candidate_name: candidateName,
        interviewer_name: interviewerName,
        // Session metadata with all IDs
        session_metadata: {
          resumeId: sessionMetadata.resumeId,
          jdId: sessionMetadata.jdId,
          interviewerId: sessionMetadata.interviewerId,
          candidateId: sessionMetadata.candidateId,
          organizationId: sessionMetadata.organizationId,
          sessionDuration: sessionMetadata.sessionDuration, // 1 hour
          maxDuration: sessionMetadata.maxDuration, // 1 hour in milliseconds
          sessionStartTime: new Date().toISOString(),
          participants: sessionMetadata.participants
        },
        // Interview settings
        interview_settings: {
          duration_minutes: 60, // 1 hour
          auto_transcribe: true,
          video_analysis: true,
          behavioral_analysis: true,
          allow_screen_share: true
        }
      };
      
      console.log('[RightSidebar] Creating session with comprehensive data:', sessionData);
      
      const response = await fetch(`${API_BASE_URL}/start_recording`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sessionData)
      });
      
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.message || `Failed to generate session: HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      console.log('[RightSidebar] Backend response:', data);
      
      // Check for different possible session_id field names
      const generatedSessionId = data.session_id || data.sessionId || data.session || data.id;
      console.log('[RightSidebar] Extracted sessionId:', generatedSessionId);
      
      if (!generatedSessionId) {
        throw new Error('No session ID received from backend');
      }
      
      const generatedSessionLink = `${window.location.origin}/candidate?session_id=${generatedSessionId}`;
      
      console.log('[RightSidebar] Setting sessionId:', generatedSessionId);
      console.log('[RightSidebar] Setting sessionLink:', generatedSessionLink);
      
      // Use a more robust state update approach
      setSessionId(generatedSessionId);
      sessionIdRef.current = generatedSessionId; // Update ref immediately
      setSessionLink(generatedSessionLink);
      setShowSessionLink(true);
      
      // Update session metadata with the generated session ID and start time
      setSessionMetadata(prev => ({
        ...prev,
        sessionId: generatedSessionId,
        sessionStartTime: new Date().toISOString()
      }));
      
      // Store session data in localStorage for persistence
      localStorage.setItem('currentSessionMetadata', JSON.stringify({
        ...sessionMetadata,
        sessionId: generatedSessionId,
        sessionStartTime: new Date().toISOString(),
        sessionLink: generatedSessionLink
      }));
      
      // Verify state updates with multiple checks
      setTimeout(() => {
        console.log('[RightSidebar] State after timeout - sessionId:', generatedSessionId);
        // Force another check
        setSessionId(prevId => {
          console.log('[RightSidebar] Previous sessionId:', prevId, 'New sessionId:', generatedSessionId);
          return prevId || generatedSessionId;
        });
      }, 50);
      
      setTimeout(() => {
        console.log('[RightSidebar] Final state check - sessionId:', generatedSessionId);
      }, 200);
      
      console.log('[RightSidebar] Session link generated successfully');
    } catch (error) {
      console.error('[RightSidebar] Error generating session link:', error);
      setLocalError(`Failed to generate session link: ${error.message}`);
    } finally {
      setIsGeneratingSession(false);
    }
  }, [candidateName, API_BASE_URL, isGeneratingSession]);

  const copySessionLink = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(sessionLink);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      setLocalError('Failed to copy session link to clipboard');
    }
  }, [sessionLink]);

  const getMediaStream = useCallback(async (video = true, audio = true) => {
    try {
      console.log('[RightSidebar] 🎥 Requesting media stream with video:', video, 'audio:', audio);
      
      // Check if browser supports getUserMedia
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Your browser does not support camera/microphone access. Please use a modern browser like Chrome, Firefox, or Edge.');
      }

      let stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video, audio });
      } catch (mediaError) {
        // Specific error handling for different permission errors
        if (mediaError.name === 'NotAllowedError' || mediaError.name === 'PermissionDeniedError') {
          console.error('[RightSidebar] ❌ Permission denied:', mediaError);
          throw new Error('Camera/microphone permission denied. Please click the camera icon in your browser\'s address bar and allow access.');
        } else if (mediaError.name === 'NotFoundError' || mediaError.name === 'DevicesNotFoundError') {
          console.error('[RightSidebar] ❌ No devices found:', mediaError);
          throw new Error('No camera or microphone found. Please connect a camera/microphone.');
        } else if (mediaError.name === 'NotReadableError' || mediaError.name === 'TrackStartError') {
          console.error('[RightSidebar] ❌ Device in use:', mediaError);
          throw new Error('Camera/microphone is already in use by another application.');
        } else {
          console.error('[RightSidebar] ❌ Media error:', mediaError);
          throw new Error(`Failed to access camera/microphone: ${mediaError.message || 'Unknown error'}`);
        }
      }
      
      // Verify stream quality
      console.log('[RightSidebar] 📹 Media stream obtained:', {
        id: stream.id,
        active: stream.active,
        tracks: stream.getTracks().length,
        videoTracks: stream.getVideoTracks().length,
        audioTracks: stream.getAudioTracks().length,
        trackDetails: stream.getTracks().map(track => ({
          kind: track.kind,
          enabled: track.enabled,
          readyState: track.readyState,
          id: track.id,
          settings: track.getSettings ? track.getSettings() : 'not available'
        }))
      });
      
      // Ensure video tracks are enabled
      stream.getVideoTracks().forEach(track => {
        if (!track.enabled) {
          console.warn('[RightSidebar] ⚠️ Video track was disabled, enabling it');
          track.enabled = true;
        }
      });
      
      setMediaStream(stream);
      setIsCamOn(!!stream.getVideoTracks()[0]?.enabled);
      setIsMicOn(!!stream.getAudioTracks()[0]?.enabled);
      console.log('[RightSidebar] ✅ Media stream state updated - cam:', !!stream.getVideoTracks()[0]?.enabled, 'mic:', !!stream.getAudioTracks()[0]?.enabled);
      
      // Add event listeners to track if stream becomes inactive
      stream.getTracks().forEach(track => {
        track.addEventListener('ended', () => {
          console.warn('[RightSidebar] ⚠️ Track ended unexpectedly:', track.kind, track.id);
        });
      });
      
      return stream;
    } catch (err) {
      console.error("[RightSidebar] ❌ Error getting media stream:", err);
      setLocalError(err.message || "Failed to access media devices. Please check your permissions.");
      return null;
    }
  }, []);

  const handleStartRecordingClick = useCallback(async () => {
    try {
      setIsInitializing(true);
      setLocalError('');
      const stream = await getMediaStream(true, true);
      if (stream) {
        await startRecordingHook(candidateName);
        setShowVideoSection(true);
      }
    } catch (error) {
      setLocalError(error.message);
    } finally {
      setIsInitializing(false);
    }
  }, [startRecordingHook, candidateName, getMediaStream]);

  const joinSession = useCallback(async () => {
    // CRITICAL FIX: Always use the latest sessionId from state, not cached ref
    let currentSessionId = sessionId; // Remove fallback to sessionIdRef.current
    
    if (!currentSessionId && sessionLink) {
      // Extract sessionId from sessionLink as fallback
      const urlParams = new URLSearchParams(sessionLink.split('?')[1]);
      currentSessionId = urlParams.get('session_id');
      console.log('[RightSidebar] Extracted sessionId from sessionLink:', currentSessionId);
      
      if (currentSessionId) {
        setSessionId(currentSessionId);
        sessionIdRef.current = currentSessionId;
      }
    }
    
    console.log('[RightSidebar] Using sessionId for joining:', currentSessionId);
    
    if (currentSessionId) {
      try {
        setIsInitializing(true);
        setLocalError('');
        const stream = await getMediaStream(true, true);
        if (stream) {
          // Pass the sessionId to startRecordingHook so it uses the same session
          await startRecordingHook(candidateName, currentSessionId);
          setShowVideoSection(true);
        }
      } catch (error) {
        setLocalError('Failed to join session: ' + error.message);
        setShowVideoSection(true);
      } finally {
        setIsInitializing(false);
      }
    } else {
      setLocalError('No session ID available. Please generate a session link first.');
    }
  }, [sessionId, sessionLink, startRecordingHook, candidateName, getMediaStream]);

  const handleStopRecordingClick = useCallback(async () => {
    await stopRecordingHook();
    if (mediaStream) {
      mediaStream.getTracks().forEach(track => track.stop());
    }
    setIsCamOn(false);
    setIsMicOn(false);
    setShowVideoSection(false);
    // Clear session data when stopping
    setSessionId('');
    sessionIdRef.current = ''; // Clear ref as well
    setSessionLink('');
    setShowSessionLink(false);
  }, [stopRecordingHook, mediaStream]);

  const handleToggleMic = useCallback(() => {
    if (mediaStream) {
      mediaStream.getAudioTracks().forEach(track => (track.enabled = !track.enabled));
      setIsMicOn(prev => !prev);
    }
  }, [mediaStream]);

  const handleToggleCam = useCallback(() => {
    if (mediaStream) {
      mediaStream.getVideoTracks().forEach(track => (track.enabled = !track.enabled));
      setIsCamOn(prev => !prev);
    }
  }, [mediaStream]);

  // QA Evaluation functions
  const handleEvaluateQA = useCallback(async (questionText, answerText, indexInHistory) => {
    try {
      console.log('Evaluating QA pair...');
      const response = await fetch(`${API_BASE_URL}/evaluate_QA`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: questionText, answer: answerText }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(`Failed to evaluate QA: ${errorData.error || response.statusText}`);
      }
      const data = await response.json();
      console.log('Evaluation result:', data);

      setQaHistory(prev => {
        const updatedHistory = [...prev];
        if (updatedHistory[indexInHistory]) {
          updatedHistory[indexInHistory] = {
            ...updatedHistory[indexInHistory],
            evaluation: data,
          };
        }
        return updatedHistory;
      });

      setScore(prev => ({
        correct: prev.correct + (data.mark === 'correct' ? 1 : 0),
        total: prev.total + 1,
      }));
    } catch (err) {
      console.error('Error evaluating QA:', err);
      setLocalError(`Failed to evaluate QA: ${err.message}`);
    }
  }, [API_BASE_URL]);

  const handleMapClick = useCallback(async () => {
    setScore({ correct: 0, total: 0 }); // Reset score before re-evaluating

    const historyToEvaluate = [...qaHistory];
    for (let i = 0; i < historyToEvaluate.length; i++) {
      const currentEntry = historyToEvaluate[i];
      if (currentEntry.speaker === 'Candidate' && !currentEntry.evaluation && i > 0 && historyToEvaluate[i - 1].speaker === 'recruiter') {
        const questionText = historyToEvaluate[i - 1].message;
        const answerText = currentEntry.message;
        await handleEvaluateQA(questionText, answerText, i);
      }
    }
  }, [qaHistory, handleEvaluateQA]);

  // Debug useEffect to monitor qaHistory changes
  useEffect(() => {
    console.log('[RightSidebar] 📝 qaHistory updated:', qaHistory.length, 'entries');
    if (qaHistory.length > 0) {
      console.log('[RightSidebar] 📝 Latest entry:', qaHistory[qaHistory.length - 1]);
    }
  }, [qaHistory]);

  return (
    <div className="min-h-screen bg-gray-100">
             {showVideoSection && sessionId && (
             <VideoSession
             sessionId={sessionId}
             candidateName={candidateName}
             interviewerName={interviewerName}
             timer={timer}
             stopRecording={handleStopRecordingClick}
             mediaStream={mediaStream}
             localVideoRef={videoRef}
             remoteVideoRef={remoteVideoRef}
             detectionMetrics={detectionMetrics}
             isMicOn={isMicOn}
             isCamOn={isCamOn}
             alerts={alerts}
             handleToggleMic={handleToggleMic}
             handleToggleCam={handleToggleCam}
               onTranscriptReceivedRef={onTranscriptReceivedRef}
               />
      )}
      {showVideoSection && !sessionId && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-md border-b border-gray-200 shadow-xl p-6">
          <div className="max-w-full mx-auto">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-xl font-bold text-gray-800">JD Interview</h2>
              <div className="flex items-center space-x-2">
                <div className="w-3 h-3 rounded-full bg-red-500"></div>
                <span className="text-sm text-gray-600">No Session ID</span>
              </div>
            </div>
            <div className="text-center py-8">
              <p className="text-gray-600 mb-4">No valid session ID available.</p>
              <p className="text-sm text-gray-500">Please generate a session link first by clicking "Start Interview".</p>
            </div>
          </div>
        </div>
      )}
      <div className={`bg-white shadow-xl transition-all duration-300 overflow-y-auto border-l w-full ${showVideoSection ? 'pt-[0px]' : ''}`}>
        <div className="p-0 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <div className="w-12 h-8 bg-green-600 rounded-full flex items-center justify-center text-white mr-2 font-medium">
                {candidateName.charAt(0).toUpperCase()}
              </div>
              <div className="flex-grow">
                <h3 className="font-semibold text-gray-800">{candidateName}</h3>
                <p className="text-sm text-gray-600">Candidate</p>
              </div>
            </div>
            <div className="flex items-center space-x-3">
            {isRecording && (
            <div className="flex items-center bg-white rounded-lg px-3 py-1 border border-gray-200 shadow-sm">
            <span className="text-red-500 animate-pulse mr-1">⬤</span>
            <span className="text-gray-800 font-medium">{timer}</span>
            </div>
            )}
               <button
                 onClick={() => setShowSessionManager(!showSessionManager)}
                 className={`p-2 rounded-lg transition-colors ${
                   showSessionManager 
                     ? 'bg-blue-500 text-white' 
                     : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                 }`}
                 title="Session Management"
               >
                 <Settings size={16} />
               </button>

            </div>
          </div>
          {showSessionLink && (
            <div className="mt-4 p-4 bg-white border border-gray-200 rounded-lg shadow-sm">
              <h4 className="font-semibold text-gray-800 mb-2">Session Link Generated</h4>
              <div className="flex items-center space-x-2 mb-3">
                <input
                  type="text"
                  value={sessionLink}
                  readOnly
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm bg-gray-50"
                />
                <button
                  onClick={copySessionLink}
                  className="px-3 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 transition-colors flex items-center space-x-1"
                >
                  <Copy size={16} />
                  <span>{copied ? 'Copied!' : 'Copy'}</span>
                </button>
              </div>
              <div className="flex items-center justify-between">
                <p className="text-sm text-gray-600">
                  Share this link with the candidate to start the interview
                </p>
                <button
                  onClick={joinSession}
                  className="px-4 py-2 bg-green-500 text-white rounded-md hover:bg-green-600 transition-colors flex items-center space-x-1"
                >
                  <ExternalLink size={16} />
                  <span>Join Session</span>
                </button>
              </div>
            </div>
          )}
          {(isInitializing || recordingState === 'connecting') && (
            <div className="mt-2 p-2 bg-blue-50 text-blue-700 rounded-md border border-blue-200 text-sm">
              <div className="flex items-center">
                <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-600 mr-2"></div>
                <p>
                  {isInitializing ? 'Initializing AI models and system components...' : 'Connecting to recording service...'}
                </p>
              </div>
            </div>
          )}
          {localError && (
            <div className="mt-2 p-2 bg-red-50 text-red-700 rounded-md border border-red-200 text-sm">
              <p>{localError}</p>
            </div>
          )}
        </div>

        {/* Session Manager Component */}
        <SessionManager 
          sessionMetadata={sessionMetadata}
          isVisible={showSessionManager}
        />
        
        {/* Video Session Component */}
        {showVideoSection && (
          <>
            {/* Video Display Section - Moved to top */}
            {/* <div className="bg-gray-100 p-4">
              <div className="max-w-6xl mx-auto">
                <div className="grid grid-cols-2 gap-4">
                 
                  <div className="bg-black rounded-lg overflow-hidden relative aspect-video">
                    <video
                      ref={videoRef}
                      autoPlay
                      muted
                      playsInline
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute bottom-2 left-2 bg-black bg-opacity-50 text-white px-2 py-1 rounded text-sm">
                      {interviewerName} (You)
                    </div>
                  </div>
                  
             
                  <div className="bg-gray-800 rounded-lg overflow-hidden relative aspect-video">
                    <video
                      ref={remoteVideoRef}
                      autoPlay
                      playsInline
                      className="w-full h-full object-cover"
                    />
                    <div className="absolute bottom-2 left-2 bg-black bg-opacity-50 text-white px-2 py-1 rounded text-sm">
                      {candidateName}
                    </div>
                    {!remoteVideoRef.current?.srcObject && (
                      <div className="absolute inset-0 flex items-center justify-center text-white">
                        <div className="text-center">
                          <div className="w-16 h-16 bg-gray-600 rounded-full flex items-center justify-center mb-2 mx-auto">
                            <span className="text-2xl font-bold">{candidateName.charAt(0)}</span>
                          </div>
                          <p>Waiting for candidate to join...</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div> */}
            
            <VideoSession
              sessionId={sessionId}
              candidateName={candidateName}
              interviewerName={interviewerName}
              timer={timer}
              stopRecording={handleStopRecordingClick}
              mediaStream={mediaStream}
              localVideoRef={videoRef}
              remoteVideoRef={remoteVideoRef}
              detectionMetrics={detectionMetrics}
              isMicOn={isMicOn}
              isCamOn={isCamOn}
              alerts={alerts}
              handleToggleMic={handleToggleMic}
              handleToggleCam={handleToggleCam}
              onTranscriptReceivedRef={onTranscriptReceivedRef}
            />
            

          </>
        )}

        <Dashboards
          resumeId={sessionMetadata.resumeId}
          initialData={processedData}
          analysisData={processedData}
          hasGeneratedDashboard={hasGeneratedDashboard}
           selectedFile={selectedFile}  
          selectedDashboardId={selectedDashboardId}
          setSelectedDashboardId={setSelectedDashboardId}
          qaHistory={qaHistory}
          score={score}
          error={localError}
          handleMapClick={handleMapClick}
        />
      </div>
    </div>
  );
}

RightSidebar.propTypes = {
  analysisData: PropTypes.object,
  hasGeneratedDashboard: PropTypes.bool
};
