import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp, ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { ApiError } from "./lib/api";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // A 4xx answer will not change on retry; show it at once.
      retry: (failures, error) =>
        !(error instanceof ApiError && error.status < 500) && failures < 3,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConfigProvider
      locale={zhCN}
      button={{ autoInsertSpace: false }}
      theme={{
        // Text colors meet WCAG AA (4.5:1) on white; antd's defaults for links, secondary,
        // tertiary, placeholder, warning, success and error text do not.
        token: {
          colorPrimary: "#0d6b73",
          colorLink: "#0d6b73",
          colorTextSecondary: "rgba(0, 0, 0, 0.65)",
          colorTextDescription: "rgba(0, 0, 0, 0.65)",
          colorTextTertiary: "rgba(0, 0, 0, 0.6)",
          colorTextPlaceholder: "rgba(0, 0, 0, 0.55)",
          colorWarning: "#8f5600",
          colorSuccess: "#237804",
          colorError: "#cf1322",
          borderRadius: 6,
        },
        // Preset tag text is shade 7 of its palette; shade 9 reaches 4.5:1 on the tag fill.
        components: {
          Tag: {
            gold7: "#874d00",
            green7: "#135200",
            red7: "#a8071a",
            blue7: "#003eb3",
            volcano7: "#871400",
            purple7: "#391085",
            // Status tags derive their fill from the darker seed colors above, which comes
            // out grey; pin the light fills and dark text.
            colorSuccess: "#135200",
            colorSuccessBg: "#f6ffed",
            colorSuccessBorder: "#b7eb8f",
            colorError: "#a8071a",
            colorErrorBg: "#fff1f0",
            colorErrorBorder: "#ffa39e",
            colorWarning: "#874d00",
            colorWarningBg: "#fffbe6",
            colorWarningBorder: "#ffe58f",
            colorInfo: "#003eb3",
            colorInfoBg: "#e6f4ff",
            colorInfoBorder: "#91caff",
          },
        },
      }}
    >
      <AntApp>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </AntApp>
    </ConfigProvider>
  </StrictMode>,
);
