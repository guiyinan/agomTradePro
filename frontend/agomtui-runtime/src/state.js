export function createRuntimeState(initial = {}) {
    return {
        catalog: null,
        screen: null,
        clientPage: 1,
        clientPageSize: 100,
        ...initial,
    };
}

export function resetClientPage(state) {
    state.clientPage = 1;
    return state;
}
