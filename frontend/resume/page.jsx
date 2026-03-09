

"use client";
import React, { useState, useEffect } from "react";
import Sidebar from "../rightsidebar/sidebar";
import RightSidebar from "../rightsidebar/index";

export default function ResumePage({ jdId, selectedFile, onClose }) {
  const [analysisData, setAnalysisData] = useState(null);
  const [selectedDashboardId, setSelectedDashboardId] = useState(null);
  const [sharedValue, setSharedValue] = useState(null);
  const [shouldDispatch, setShouldDispatch] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [roles, setRoles] = useState([]);
  const [skillsData, setSkillsData] = useState([]);
  const [selectedRoles, setSelectedRoles] = useState([]);
  const [dashboardData, setDashboardData] = useState([]);
  const [showThreshold, setShowThreshold] = useState(true);
  const [showJobDescription, setShowJobDescription] = useState(true);
  const [showResume, setShowResume] = useState(true);
  const [showCommunicationSkills, setShowCommunicationSkills] = useState(true);
  const [showCoding, setShowCoding] = useState(true);
  const [showBehaviouralSkills, setShowBehaviouralSkills] = useState(true);
  const [showCommondashBoard, setShowCommondashBoard] = useState(true);
  const [showHrSystem, setShowHrSystem] = useState(true);
  const [viewItems, setViewItems] = useState([]);
  const [showProjectDashboard, setShowProjectDashboard] = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [isPageVisible, setIsPageVisible] = useState(true);

  // Prepare analysisData from resume (initial data)
useEffect(() => {
  if (selectedFile) {
    const analysisDataObj = {
      file: selectedFile,
      type: "resume",
      content: selectedFile.content || selectedFile.extracted_text || "",
      name: selectedFile.name || selectedFile.candidateName || `Resume-${selectedFile.resumeId}`,
      isInitialData: true,
      dashboardContents: selectedFile.dashboardContents || [],
      dashboardContent: selectedFile.dashboardContent || null,
      thresholdData: selectedFile.thresholdData || selectedFile.threshold_result || null,
      selectionScore: selectedFile.selectionScore || selectedFile.selection_score || null,
      rejectionScore: selectedFile.rejectionScore || selectedFile.rejection_score || null,
      candidateName: selectedFile.candidateName || selectedFile.candidate_name || null,
      candidateId: selectedFile.candidateId || selectedFile.candidate_id || null,
      resumeId: selectedFile.resumeId || selectedFile.resume_id || null,
      extractedText: selectedFile.content || selectedFile.extracted_text || null,
      analysisResult: selectedFile.analysis_result || null,
      jobId: selectedFile.job_id || null, // keep for JD tab
      email: selectedFile.email || null,
      role: selectedFile.role || null,
      analytics: selectedFile.analytics || [],
      jobDetails: selectedFile.jobDetails || null,
    };

    setAnalysisData(analysisDataObj);

    // For Dashboard.jsx, we can pass either jobId or resumeId
    // setSelectedDashboardId(selectedFile.resumeId || selectedFile.resume_id);
    const firstDashboardId =
      analysisDataObj.dashboardContents?.[0]?.dashboard_id ||
      analysisDataObj.dashboardContents?.[0]?.id ||
      null;

    setSelectedDashboardId(firstDashboardId);
    setUploadedFile(selectedFile);


  }
}, [selectedFile]);

  // Trigger dashboard dispatch if needed (like JD page)
  useEffect(() => {
    if (!sharedValue || !analysisData?.resumeId) return;
    setShouldDispatch(true);
  }, [sharedValue, analysisData]);

  useEffect(() => {
    if (shouldDispatch) {
      window.dispatchEvent(
        new CustomEvent("createDashboards", { detail: { scale: sharedValue } })
      );
      setSharedValue(null);
      setShouldDispatch(false);
    }
  }, [shouldDispatch]);

  const handleSelectedRoles = (roles) => {
    setSelectedRoles(roles);
  };

  const handleCreate = (data) => {
    if (!analysisData) return;

    // Support modification by either `id` or `dashboard_id` (backend vs frontend shapes)
    if (data.dashboardId) {
      setAnalysisData((prev) => {
        const updatedContents = prev.dashboardContents.map((db) => {
          const matches = db.id === data.dashboardId || db.dashboard_id === data.dashboardId;
          if (!matches) return db;

          // Update both common shapes
          const updated = { ...db, content: data.prompt };
          if (updated.dashboard_id === undefined && updated.id !== undefined) updated.dashboard_id = updated.id;
          if (updated.id === undefined && updated.dashboard_id !== undefined) updated.id = updated.dashboard_id;
          return updated;
        });
        return { ...prev, dashboardContents: updatedContents };
      });
      return;
    }

    if (data.prompt) {
      // Create new dashboard using the same shape as the JD/Dashboards component
      const newDashboard = {
        dashboard_id: `local-${Date.now()}`,
        dashboard_title: `Dashboard ${analysisData.dashboardContents.length + 1}`,
        overview: data.prompt,
        content: data.prompt,
      };

      setAnalysisData((prev) => {
        const alreadyExists = prev.dashboardContents.some((d) => d.dashboard_title === newDashboard.dashboard_title || d.title === newDashboard.dashboard_title);
        if (alreadyExists) return prev;
        return { ...prev, dashboardContents: [...prev.dashboardContents, newDashboard] };
      });
    }
  };

  const handleClosePage = () => {
    setIsPageVisible(false);
    if (onClose) onClose();
  };

  if (!isPageVisible) return null;
  const hasGeneratedDashboard = analysisData?.dashboardContents?.length > 0;

  return (
    <div className="flex flex-col bg-indigo-50 overflow-hidden min-h-screen">
      <main className="flex flex-col w-full h-full">
        <div className="space-y-2 bg-white rounded-lg shadow-md mx-0 pt-0 h-full">
          <section className="flex flex-col justify-center self-center p-0.5 w-full bg-white h-full">
            <div className="flex relative h-full">
              {/* Sidebar hover trigger */}
              <div
                className="fixed left-0 top-0 h-full w-4 z-50 cursor-pointer"
                onMouseEnter={() => setIsSidebarOpen(true)}
              />
              {/* Sidebar */}
              <div
                className="transition-all duration-300 ease-in-out shrink-0 overflow-hidden h-full"
                style={{ width: isSidebarOpen ? "18rem" : "0px" }}
                onMouseLeave={() => setIsSidebarOpen(false)}
              >
                <Sidebar
                  roles={roles}
                  skills_data={skillsData}
                  sendSelectedRoles={handleSelectedRoles}
                  sendRangeValue={setSharedValue}
                  onCreate={handleCreate}
                  analysisData={analysisData}
                  resumeData={analysisData}
                  selectedDashboardId={selectedDashboardId}
                  setSelectedDashboardId={setSelectedDashboardId}
                />
              </div>
              {/* Right Sidebar */}
              <div className="flex-1 flex flex-col h-full overflow-y-auto bg-gray-100">
                <RightSidebar
                  analysisData={analysisData}
                  hasGeneratedDashboard={hasGeneratedDashboard}
                   selectedFile={selectedFile}  
                  selectedDashboardId={selectedDashboardId}
                  setSelectedDashboardId={setSelectedDashboardId}
                />
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}