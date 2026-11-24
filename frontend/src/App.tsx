import { lazy, Suspense, useCallback, useState } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router";
import { AuthProvider } from "./auth/AuthProvider";
import { homePath, useAuth } from "./auth/context";
import { ClientOrGuest, RequireRole } from "./auth/RequireRole";
import { Layout } from "./components/Layout";
import {
  chooseLanguage,
  currentLanguage,
  type Language,
} from "./i18n/language";
import { LanguageContext } from "./i18n/LanguageContext";
import { t } from "./i18n/lv";
import { usePageTitle } from "./i18n/usePageTitle";
import { Skeleton } from "./components/Skeleton";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { CataloguePage as ClientCataloguePage } from "./pages/client/CataloguePage";
import { ClientHomePage } from "./pages/client/ClientHomePage";
import { OrderStartPage } from "./pages/client/OrderStartPage";
import { SpecialisationPage } from "./pages/client/SpecialisationPage";
import { MasterHomePage } from "./pages/master/MasterHomePage";
import { ClientRequestPage } from "./pages/client/ClientRequestPage";

// Role areas load on demand: guests and clients never download the admin or master code.
const AdminDashboardPage = lazy(() =>
  import("./pages/admin/AdminDashboardPage").then((m) => ({
    default: m.AdminDashboardPage,
  })),
);
const AdminUsersPage = lazy(() =>
  import("./pages/admin/AdminUsersPage").then((m) => ({
    default: m.AdminUsersPage,
  })),
);
const CataloguePage = lazy(() =>
  import("./pages/admin/catalogue/CataloguePage").then((m) => ({
    default: m.CataloguePage,
  })),
);
const QualificationsPage = lazy(() =>
  import("./pages/admin/catalogue/QualificationsPage").then((m) => ({
    default: m.QualificationsPage,
  })),
);
const MasterDetailPage = lazy(() =>
  import("./pages/admin/masters/MasterDetailPage").then((m) => ({
    default: m.MasterDetailPage,
  })),
);
const MastersPage = lazy(() =>
  import("./pages/admin/masters/MastersPage").then((m) => ({
    default: m.MastersPage,
  })),
);
const ReviewQueuePage = lazy(() =>
  import("./pages/admin/masters/ReviewQueuePage").then((m) => ({
    default: m.ReviewQueuePage,
  })),
);
const TransferPage = lazy(() =>
  import("./pages/admin/catalogue/TransferPage").then((m) => ({
    default: m.TransferPage,
  })),
);
const MasterCapabilitiesPage = lazy(() =>
  import("./pages/master/MasterCapabilitiesPage").then((m) => ({
    default: m.MasterCapabilitiesPage,
  })),
);
const MasterWorkPage = lazy(() =>
  import("./pages/master/MasterWorkPage").then((m) => ({
    default: m.MasterWorkPage,
  })),
);
const MasterOrderPage = lazy(() =>
  import("./pages/master/MasterOrderPage").then((m) => ({
    default: m.MasterOrderPage,
  })),
);
const MasterCommissionPage = lazy(() =>
  import("./pages/master/MasterCommissionPage").then((m) => ({
    default: m.MasterCommissionPage,
  })),
);
const MediaPage = lazy(() =>
  import("./pages/admin/content/MediaPage").then((m) => ({
    default: m.MediaPage,
  })),
);
const TermsPage = lazy(() =>
  import("./pages/admin/work/TermsPage").then((m) => ({
    default: m.TermsPage,
  })),
);
const ContentEditPage = lazy(() =>
  import("./pages/admin/content/ContentPages").then((m) => ({
    default: m.ContentEditPage,
  })),
);
const ContentListPage = lazy(() =>
  import("./pages/admin/content/ContentPages").then((m) => ({
    default: m.ContentListPage,
  })),
);
const CommissionListPage = lazy(() =>
  import("./pages/admin/work/CommissionPages").then((m) => ({
    default: m.CommissionListPage,
  })),
);
const CommissionMasterPage = lazy(() =>
  import("./pages/admin/work/CommissionPages").then((m) => ({
    default: m.CommissionMasterPage,
  })),
);
const RequestDetailPage = lazy(() =>
  import("./pages/admin/work/RequestsPages").then((m) => ({
    default: m.RequestDetailPage,
  })),
);
const RequestsListPage = lazy(() =>
  import("./pages/admin/work/RequestsPages").then((m) => ({
    default: m.RequestsListPage,
  })),
);

function HomeRedirect() {
  const { user, ready } = useAuth();
  if (!ready) return <Skeleton variant="page" />;
  // Guests start in the public catalogue; signed-in users in their own area.
  return <Navigate to={user ? homePath(user.role) : "/pakalpojumi"} replace />;
}

function NotFound() {
  usePageTitle(t.notFound);
  return (
    <section className="notfound">
      <span className="code" aria-hidden="true">
        404
      </span>
      <h1>{t.notFound}</h1>
      <p className="lead">{t.pages.notFoundHint}</p>
      <div className="nav-cards">
        <Link to="/" className="nav-card">
          <strong>{t.backHome} →</strong>
        </Link>
        <Link to="/pakalpojumi" className="nav-card">
          <strong>{t.pages.notFoundServices} →</strong>
        </Link>
      </div>
    </section>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Skeleton variant="page" />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomeRedirect />} />
          <Route path="login" element={<LoginPage />} />
          <Route
            path="register/client"
            element={<RegisterPage role="client" />}
          />
          <Route
            path="register/master"
            element={<RegisterPage role="master" />}
          />
          {/* Public catalogue and ordering are open to guests: the order form creates a client account from the
              contact details (owner decision 2026-11-24); the W-ID is kept through sign-in. */}
          <Route path="pakalpojumi" element={<ClientCataloguePage />} />
          <Route path="pakalpojumi/:id" element={<SpecialisationPage />} />
          <Route
            path="pieteikums/jauns"
            element={
              <ClientOrGuest>
                <OrderStartPage />
              </ClientOrGuest>
            }
          />
          <Route
            path="client"
            element={
              <RequireRole role="client">
                <ClientHomePage />
              </RequireRole>
            }
          />
          <Route
            path="client/pieteikumi/:id"
            element={
              <RequireRole role="client">
                <ClientRequestPage />
              </RequireRole>
            }
          />
          <Route
            path="master/darbs"
            element={
              <RequireRole role="master">
                <MasterWorkPage />
              </RequireRole>
            }
          />
          <Route
            path="master/pasutijumi/:id"
            element={
              <RequireRole role="master">
                <MasterOrderPage />
              </RequireRole>
            }
          />
          <Route
            path="master/komisija"
            element={
              <RequireRole role="master">
                <MasterCommissionPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/content"
            element={
              <RequireRole role="admin">
                <ContentListPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/content/:specId"
            element={
              <RequireRole role="admin">
                <ContentEditPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/media"
            element={
              <RequireRole role="admin">
                <MediaPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/terms"
            element={
              <RequireRole role="admin">
                <TermsPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/commission"
            element={
              <RequireRole role="admin">
                <CommissionListPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/commission/:id"
            element={
              <RequireRole role="admin">
                <CommissionMasterPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/requests"
            element={
              <RequireRole role="admin">
                <RequestsListPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/requests/:id"
            element={
              <RequireRole role="admin">
                <RequestDetailPage />
              </RequireRole>
            }
          />
          <Route
            path="master"
            element={
              <RequireRole role="master">
                <MasterHomePage />
              </RequireRole>
            }
          />
          <Route
            path="master/capabilities"
            element={
              <RequireRole role="master">
                <MasterCapabilitiesPage />
              </RequireRole>
            }
          />
          <Route
            path="admin"
            element={
              <RequireRole role="admin">
                <AdminDashboardPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/users"
            element={
              <RequireRole role="admin">
                <AdminUsersPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/masters"
            element={
              <RequireRole role="admin">
                <MastersPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/masters/:id"
            element={
              <RequireRole role="admin">
                <MasterDetailPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/review-queue"
            element={
              <RequireRole role="admin">
                <ReviewQueuePage />
              </RequireRole>
            }
          />
          <Route
            path="admin/catalogue"
            element={
              <RequireRole role="admin">
                <CataloguePage />
              </RequireRole>
            }
          />
          <Route
            path="admin/catalogue/qualifications"
            element={
              <RequireRole role="admin">
                <QualificationsPage />
              </RequireRole>
            }
          />
          <Route
            path="admin/catalogue/transfer"
            element={
              <RequireRole role="admin">
                <TransferPage />
              </RequireRole>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App() {
  // The language is state at the root: a switch re-renders every page in the new language.
  const [language, setLanguageState] = useState<Language>(currentLanguage);
  const setLanguage = useCallback((next: Language) => {
    chooseLanguage(next);
    setLanguageState(next);
  }, []);
  return (
    <LanguageContext.Provider value={{ language, setLanguage }}>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </LanguageContext.Provider>
  );
}
