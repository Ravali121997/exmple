"use client";
import React, { useState, useEffect } from "react";
// import Sidebar from "../rightsidebar/sidebar";
// import RightSidebar from "../rightsidebar/index";
import Sidebar from "./rightsidebar/sidebar";
import RightSidebar from "./rightsidebar/index";

export default function CS({ jdId, selectedFile,resumeData, onClose }) {
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
  // const [hasGeneratedDashboard, setHasGeneratedDashboard] = useState(false);

  const handleSelectedRoles = (roles) => {
    setSelectedRoles(roles);
  };
  console.log("💡 jdId:", jdId, "selectedFile:", selectedFile);
//   useEffect(() => {
//     console.log("📁 selectedFile changed:", selectedFile);
//   if (selectedFile) {
//     const analysisDataObj = {
//       file: selectedFile,
//       // job_id: jdId,
//       job_id: selectedFile.jobId || jdId,
//       type: selectedFile.type || "job-description",
//       content: selectedFile.content || "",
//       name: selectedFile.name || `JD-${jdId}`,
//       isInitialData: true,
//       dashboardContents: selectedFile.dashboardContents || [],
//       dashboardContent: selectedFile.dashboardContent || null,
//       thresholdData: selectedFile.thresholdData || null,
//       selectionScore: selectedFile.selectionScore || null,
//       rejectionScore: selectedFile.rejectionScore || null,
//       resumeData: resumeData || selectedFile.resumeData || null,
//     };
//     console.log("🧩 Computed analysisDataObj:", analysisDataObj);
//     setAnalysisData(analysisDataObj);
//   }
// }, [jdId, selectedFile]);

  // Trigger dashboard generation when both JD and sharedValue are ready
//   useEffect(() => {
//     if (sharedValue && analysisData?.job_id) setShouldDispatch(true);
//     console.log("⚡ Triggering dashboard generation, sharedValue:", sharedValue, "analysisData.job_id:", analysisData.job_id);
//   }, [sharedValue, analysisData?.job_id]);

useEffect(() => {
  if (selectedFile) {
    const analysisDataObj = {
      file: selectedFile,
      job_id: selectedFile.jobId || jdId || `JD-${Date.now()}`, // fallback unique id
      type: selectedFile.type || "job-description",
      content: selectedFile.content || "",
      name: selectedFile.name || `JD-${jdId}`,
      isInitialData: true,
      dashboardContents: selectedFile.dashboardContents || [],
      dashboardContent: selectedFile.dashboardContent || null,
      thresholdData: selectedFile.thresholdData || null,
      selectionScore: selectedFile.selectionScore || null,
      rejectionScore: selectedFile.rejectionScore || null,
      resumeData: resumeData || selectedFile.resumeData || null,
    };
    console.log("🧩 Computed analysisDataObj:", analysisDataObj);
    setAnalysisData(analysisDataObj);
  }
}, [jdId, selectedFile, resumeData]);

//   useEffect(() => {
//   if (sharedValue && analysisData?.job_id) {
//     console.log("⚡ Triggering dashboard generation:", sharedValue, analysisData.job_id);
//     setShouldDispatch(true);
//   } else {
//     console.log("⚡ Dashboard generation skipped — analysisData or job_id not ready", sharedValue, analysisData);
//   }
// }, [sharedValue, analysisData?.job_id]);

// useEffect(() => {
//   if (sharedValue && analysisData?.job_id) {
//     console.log("⚡ Triggering dashboard generation:", sharedValue, analysisData.job_id);
//     setShouldDispatch(true);
//   } else {
//     console.log(
//       "⚡ Dashboard generation skipped — analysisData or job_id not ready",
//       sharedValue,
//       analysisData
//     );
//   }
// }, [sharedValue, analysisData]);

useEffect(() => {
  if (!sharedValue) {
    console.log("⏳ Waiting for sharedValue...");
    return;
  }

  if (!analysisData?.job_id) {
    console.log("⏳ Waiting for analysisData.job_id...");
    return;
  }

  console.log("⚡ Triggering dashboard generation:", sharedValue, analysisData.job_id);
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

  // Handle dashboard creation / modification
  const handleCreate = (data) => {
    console.log("📥 handleCreate received:", data);

    if (data.dashboardId) {
        console.log("🛠 Modifying existing dashboard with ID:", data.dashboardId);
      // Modify existing dashboard
      setAnalysisData((prev) => {
        const updatedContents = prev.dashboardContents.map((db, i) =>
          db.id === data.dashboardId ? { ...db, content: data.prompt } : db
        );
        console.log("🔄 Updated dashboardContents:", updatedContents);
        return { ...prev, dashboardContents: updatedContents };
      });
    } else if (data.prompt) {
         console.log("➕ Creating new dashboard with prompt:", data.prompt);
      // Create new dashboard
      const newDashboard = {
        id: Date.now(),
        title: `Dashboard ${analysisData.dashboardContents.length + 1}`,
        content: data.prompt,
      };
    //   setAnalysisData((prev) => ({
    //     ...prev,
    //     dashboardContents: [...prev.dashboardContents, newDashboard],
        // setAnalysisData((prev) => {
        // const updatedDashboards = [...prev.dashboardContents, newDashboard];
        // console.log("✅ Updated dashboardContents with new dashboard:", updatedDashboards);
        // return { ...prev, dashboardContents: updatedDashboards };
        // });
        setAnalysisData((prev) => {
  // Check if dashboard with same title already exists
      const alreadyExists = prev.dashboardContents.some(
        (d) => d.title === newDashboard.title
      );

      if (alreadyExists) {
        console.log("⚠️ Dashboard with same title already exists. Skipping append.");
        return prev; // do not append duplicate
      }

      const updatedDashboards = [...prev.dashboardContents, newDashboard];
      console.log("✅ Updated dashboardContents with new dashboard:", updatedDashboards);

      return { ...prev, dashboardContents: updatedDashboards };
    });

    }
  };

  const handleClosePage = () => {
    setIsPageVisible(false);
    if (onClose) onClose();
  };

  if (!isPageVisible) return null;
  // Derived flag for RightSidebar
  const hasGeneratedDashboard = analysisData?.dashboardContents?.length > 0;
  
  console.log("🖥 RightSidebar props:", {analysisData,
  hasGeneratedDashboard: analysisData?.dashboardContents?.length > 0,
  selectedDashboardId,});

  return (
    <div className="flex flex-col bg-indigo-50 overflow-hidden min-h-screen">
      <main className="flex flex-col w-full h-full">
        <div className="space-y-2 bg-white rounded-lg shadow-md mx-0 pt-0 h-full">
          <section className="flex flex-col justify-center self-center p-0.5 w-full bg-white h-full">
            <div className="flex relative h-full">
              {/* Sidebar */}
              {/* Hover Trigger Area */}
              <div
                className="fixed left-0 top-0 h-full w-4 z-50 cursor-pointer"
                onMouseEnter={() => setIsSidebarOpen(true)}
              />
              {/* Movable Sidebar */}
              <div
                className="transition-all duration-300 ease-in-out shrink-0  overflow-hidden h-full"
                style={{ width: isSidebarOpen ? "18rem" : "0px" }}
                onMouseLeave={() => setIsSidebarOpen(false)}
                  >
                  <Sidebar
                    roles={roles}
                    skills_data={skillsData}
                    jdId={jdId}
                    onCreate={handleCreate}
                    sendSelectedRoles={handleSelectedRoles}
                    analysisData={analysisData}
                    selectedDashboardId={selectedDashboardId}
                    setSelectedDashboardId={setSelectedDashboardId}
                    resumeData={analysisData?.resumeData}
                    sendRangeValue={setSharedValue}
                  />                
              </div>
              {/* Right Sidebar */}
              <div className="flex-1 flex flex-col h-full overflow-y-auto bg-gray-100">
                {/* <span style={{ paddingLeft: "34px", fontSize: "20px" }}>
                  JD {jdId}
                </span> */}
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
