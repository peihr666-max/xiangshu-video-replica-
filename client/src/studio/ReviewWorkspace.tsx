import { createReviewData, createReviewState, reviewUser } from "./fixtures";
import { StudioWorkspace } from "./StudioWorkspace";
import { routeFromHash } from "./state";

export default function ReviewWorkspace() {
  if (!import.meta.env.DEV) return null;
  return (
    <StudioWorkspace
      currentUser={reviewUser}
      reviewData={createReviewData()}
      initialState={createReviewState(routeFromHash(window.location.hash))}
    />
  );
}
