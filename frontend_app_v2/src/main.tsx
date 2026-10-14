import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter } from 'react-router-dom';
import { AppRuntimeProvider } from './app/AppRuntimeProvider';
import App from './App';
import './styles/tailwind.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        {/* Runtime global: satu offline queue + feedback flash (beep/haptic/overlay). */}
        <AppRuntimeProvider>
          <App />
        </AppRuntimeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
);

