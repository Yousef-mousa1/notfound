import { lazy, Suspense } from "react";
import { createBrowserRouter } from "react-router-dom";

import MainLayout from "../components/layout/MainLayout";

// Route-level code splitting: the 3D globe (three.js) and the charts
// (recharts) only load when their page is opened.
const DashboardPage = lazy(() => import("../features/dashboard/DashboardPage"));
const FireMapPage = lazy(() => import("../features/fire-map/FireMapPage"));
const CalendarPage = lazy(() => import("../features/calendar/CalendarPage"));
const AnalyticsPage = lazy(() => import("../features/analytics/AnalyticsPage"));
const ExportPage = lazy(() => import("../features/export/ExportPage"));

function PageFallback() {
  return (
    <div className="flex min-h-60 items-center justify-center">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-orange-500 border-t-transparent" />
    </div>
  );
}

const page = (element) => <Suspense fallback={<PageFallback />}>{element}</Suspense>;

const router = createBrowserRouter([
  {
    path: "/",
    element: <MainLayout />,
    children: [
      { index: true, element: page(<DashboardPage />) },
      { path: "map", element: page(<FireMapPage />) },
      { path: "calendar", element: page(<CalendarPage />) },
      { path: "analytics", element: page(<AnalyticsPage />) },
      { path: "export", element: page(<ExportPage />) },
    ],
  },
]);

export default router;
