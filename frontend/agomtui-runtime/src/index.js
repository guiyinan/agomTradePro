import { createRuntimeUrls } from "./api.js";
import { debounce } from "./events.js";
import { runtimeHooks } from "./extensions.js";
import { clientPage } from "./pagination.js";
import { mark, measure } from "./performance.js";
import { createRuntimeState, resetClientPage } from "./state.js";

globalThis.AgomTUIRuntimeCore = Object.freeze({
    clientPage,
    createRuntimeState,
    createRuntimeUrls,
    debounce,
    mark,
    measure,
    resetClientPage,
    runtimeHooks,
});
