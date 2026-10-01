import { useMutation, useQueryClient } from "@tanstack/react-query";
import { App } from "antd";

import { ApiError } from "../../lib/api";
import { errorText } from "../../lib/i18n";

/** Run a candidate action, refresh the workspace, and explain conflicts. */
export function useCandidateAction<T>(taskId: string, run: (input: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  const { message, modal } = App.useApp();
  return useMutation({
    mutationFn: run,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["candidates", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "revision_conflict") {
        modal.warning({
          title: "内容已被修改",
          content: "其他人刚刚修改了这个候选。已为您刷新，请比较最新内容后再操作。",
          okText: "刷新并比较",
          onOk: () => queryClient.invalidateQueries({ queryKey: ["candidates", taskId] }),
        });
        void queryClient.invalidateQueries({ queryKey: ["candidates", taskId] });
      } else {
        message.error(errorText(error));
      }
    },
  });
}
