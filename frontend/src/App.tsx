import { useCallback, useEffect, useMemo, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError, setToken, setUnauthorizedHandler } from './lib/api';
import { AuthContext, loadUser, saveUser } from './lib/auth';
import { DICTS, LangContext, type Lang } from './lib/i18n';
import type { Session, User } from './lib/types';
import { LoginPage } from './pages/LoginPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { DocumentPage } from './pages/DocumentPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
      refetchOnWindowFocus: false,
    },
  },
});

function loadLang(): Lang {
  try {
    return localStorage.getItem('kaagaz.lang') === 'hi' ? 'hi' : 'en';
  } catch {
    return 'en';
  }
}

export function Providers({ children, initialUser = null }: { children: React.ReactNode; initialUser?: User | null }) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [lang, setLangState] = useState<Lang>(loadLang);

  const signIn = useCallback((s: Session) => {
    setToken(s.token);
    saveUser(s.user);
    setUser(s.user);
  }, []);
  const signOut = useCallback(() => {
    setToken(null);
    saveUser(null);
    setUser(null);
    queryClient.clear();
  }, []);
  useEffect(() => setUnauthorizedHandler(signOut), [signOut]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem('kaagaz.lang', l);
    } catch {
      /* ignore */
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const auth = useMemo(() => ({ user, signIn, signOut }), [user, signIn, signOut]);
  const i18n = useMemo(() => ({ lang, t: DICTS[lang], setLang }), [lang, setLang]);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={auth}>
        <LangContext.Provider value={i18n}>{children}</LangContext.Provider>
      </AuthContext.Provider>
    </QueryClientProvider>
  );
}

function AppRoutes() {
  return (
    <AuthContext.Consumer>
      {({ user }) => (
        <Routes>
          <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
          <Route path="/" element={user ? <DocumentsPage /> : <Navigate to="/login" replace />} />
          <Route path="/documents/:id" element={user ? <DocumentPage /> : <Navigate to="/login" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      )}
    </AuthContext.Consumer>
  );
}

export default function App() {
  return (
    <Providers initialUser={loadUser()}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
