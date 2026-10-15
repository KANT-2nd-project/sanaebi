# Blind relevance review — part 3 (D07–D13)

이 문서는 D07–D13의 질문, 필수 주장, 각 passage 본문을 읽고 판단한 AI 단독 의미 관련성 검토 기록이다. 입력 passage 600개를 모두 검토했다. 점수는 질문에 대한 의미상 유용성을 기준으로 0(무관), 1(같은 주제·일반 절차), 2(직접 일부 지원·주의), 3(핵심 답 직접 지원)으로 부여했다.

## 사례별 검토 범위

| 사례 | 질문 | 검토 | 점수 분포 (0/1/2/3) | 구분한 경계 |
|---|---|---:|---|---|
| D07 | 새 SaaS 구매 승인은 났는데 계정 권한도 자동으로 생긴 거야? | 40/40 | 15 / 20 / 4 / 1 | 구매 검토 완료와 서비스 계정·권한 발급을 구분했다. 구매/사전 기술 검토만 다루는 문단은 자동 발급 여부의 직접 근거로 보지 않았다. |
| D08 | 회사 노트북을 차 안에 두고 잠깐 자리를 비워도 될까? 퇴근 뒤에는 어디에 둬야 해? | 68/68 | 52 / 13 / 2 / 1 | 차량 내 보관 금지와 퇴근 뒤 잠금 보관 장소를 각각 구분했다. 노트북 분실·일반 화면 잠금 문단은 정답으로 간주하지 않았다. |
| D09 | 가짜 로그인 페이지에 회사 비밀번호를 입력한 것 같아. 다른 서비스에도 같은 비밀번호를 썼는데 어떻게 해야 해? | 72/72 | 36 / 18 / 16 / 2 | 잘못된 곳에 입력한 뒤 즉시 사고 신고와 재사용 비밀번호 변경을 구분했다. 피싱 예방만 설명하는 문단은 사후 조치로 보지 않았다. |
| D10 | 장애 대응 때문에 긴급 권한이 필요해. 누가 승인해야 하고 사용이 끝나면 어떻게 해? | 94/94 | 39 / 49 / 5 / 1 | 긴급 권한의 공동 승인, 4시간 제한, 사용 종료 후 회수 요청 및 다음 영업일 검토를 일반 권한 신청과 구분했다. |
| D11 | 형제자매나 조부모 상을 당한 경우 회사 경조 휴가 일수와 주말 처리 기준은? | 44/44 | 28 / 12 / 0 / 4 | 형제자매·조부모의 회사 제공 경조 휴가 3근무일과 주말·공휴일 비차감을 일반 휴가·법적 권리 안내와 구분했다. |
| D12 | 회사 유료 AI 계정이면 사내 절차 문서를 붙여 넣어도 되는 거야? | 137/137 | 84 / 37 / 12 / 4 | 유료 회사 AI 플랜과 자료 허용 범위를 구분했다. 내부 문서 입력 금지 및 적법한 공개 배포본 확인과 일반 AI 사용 주의사항을 나눴다. |
| D13 | 수상한 링크에 들어가 회사 계정 정보를 입력했어. 로그인은 계속해도 돼? | 145/145 | 86 / 37 / 21 / 1 | 링크를 열기 전 예방, 자격정보 입력 후 신고, 비밀번호 교체, 오공유·저장장치 사고 절차를 구분했다. 질문의 직접 핵심은 추가 입력 중단·즉시 신고 및 IT 안내 전 의심 세션 미사용이다. |

## 바인딩 오류 감사와 수정 방식

초기 검토물에서 passage의 실제 내용과 그에 연결된 점수·이유가 어긋나는 체계적 바인딩 오류가 확인됐다. D07에서는 일부 이유가 인접 passage를 설명하는 한 칸 밀림 사례가 보고됐고, 예를 들어 `3f9d6b4471ff119494f731cd531b356f66714c08b4fba64426f70bb2089143ae`는 구매금액·사전 기술 검토 내용이므로 “구매 승인만으로 계정이 자동 발급되지 않는다”는 직접 근거가 아니다. 반면 `4b71542495b8c177215f5f80897b4e6e6b57b04e8c05fa6346850a564e747e21`는 구매 완료 후 계정이 자동 발급되지 않는 내용을 담는다. 초기 기록에서 원인을 만든 작성 코드나 정확한 오프셋 발생 지점은 조사하지 않았다.

각 변경은 질문과 본문을 실제로 대조해 판단했다. 동일한 `chunk_id`가 서로 다른 질문 사례에 반복 등장하므로 최종 범위 확인과 수정은 `(case_id, chunk_id)` 복합키로 했다. 순위·위치만으로 점수를 이동하거나 자동 키워드·임베딩·문자열 겹침으로 등급을 만들지 않았다. 아래 목록은 보존본과 현재본 사이에서 점수 또는 이유가 바뀐 D07–D13의 모든 복합키 쌍이다. 전체 이전·현재 이유는 각 JSON 파일에서 같은 복합키로 확인할 수 있다.

**보존 전 파일:** `judgments-3-before-mapping-fix.json`  
**현재 수정 파일:** `judgments-3.json`  
**범위 경계:** D14–D18은 이 검토에 포함하거나 여기서 수정하지 않았다. 해당 사례는 별도 담당자가 재검토한다.

## 변경된 복합키 쌍 전체 목록

각 항목은 `case_id / chunk_id: 이전 점수 → 현재 점수`를 나타낸다. 모든 listed pair에서 이유도 교체했다.

### D07

- `D07` / `035aef72d16ad9d706845e40b9472812ed8c5b7d4622092fe7da60d874248af3`: 2 → 2 (reason updated)
- `D07` / `0727fcac286ef07ad97abf0750f3997455792a32be480c3b83047227ea29c48c`: 1 → 1 (reason updated)
- `D07` / `0e06ddeb02b7c9a394c64d63235c50536aee41dbcff6251eccf4f2f470d65b0f`: 0 → 0 (reason updated)
- `D07` / `1252caaec75ace55a966676f033e0996318d915687d80b7e131a200cf8a617dd`: 0 → 1 (reason updated)
- `D07` / `1730f2fa4bca3c7253dcbf49a8e1632f0cff4f3eac3aab230b2f9cd8ec7585eb`: 0 → 0 (reason updated)
- `D07` / `1e0f53b17c93714252dc145e01ecc7f6db9def6bc41952aea7482e72e9b97bf5`: 1 → 1 (reason updated)
- `D07` / `2459749c6b429e956717e3812559654897f27fc3eac2b50cf811295ce75ceb63`: 0 → 0 (reason updated)
- `D07` / `2536abc35845de1680e0ab2f2fffad9359dcff9728ef16f4cf2fc3d3f3d90c1b`: 1 → 1 (reason updated)
- `D07` / `34f9645a84a07b4d58efa4030330af23159b073ae23e84c8e22ee09608d7c1c2`: 2 → 2 (reason updated)
- `D07` / `3cb860cf5e8923c35325b974326ef1956ad20b591b894ccd5b2e05c8e5b4dcc3`: 2 → 1 (reason updated)
- `D07` / `3e23709274b6dd92ed220c8e27e4813b373e03a3fda4a27c29eb8e18b731985f`: 0 → 0 (reason updated)
- `D07` / `3f9d6b4471ff119494f731cd531b356f66714c08b4fba64426f70bb2089143ae`: 3 → 1 (reason updated)
- `D07` / `42e7c00631b2f6015842b8bf9edcd70ccee5c20c6a2e6f693667ba721ddc7c94`: 1 → 0 (reason updated)
- `D07` / `46ebdeb51e7764e62b8af52a252f0def5816f541ef0567e1a456bd596aa8e82b`: 0 → 0 (reason updated)
- `D07` / `4b71542495b8c177215f5f80897b4e6e6b57b04e8c05fa6346850a564e747e21`: 0 → 3 (reason updated)
- `D07` / `5b17d55eb9caa3b325c5db76ca8a187ff21c9ea7bd6964040c81178b812dd9ec`: 2 → 1 (reason updated)
- `D07` / `614e6fdeae9ef357a95e36f414beafc9c2e2f018ac97ed58717af1070bd79c15`: 0 → 1 (reason updated)
- `D07` / `6aeca7c94f9033509c867fa52db4abc6a60426e71c7809ec933c706d47f141e1`: 0 → 0 (reason updated)
- `D07` / `6dfb75261e2d390a2c32baa301c1db29147cc063b7e5a0efebc662ffae76c4ae`: 1 → 1 (reason updated)
- `D07` / `6f4a7377a9f19cab0dcbff79f8087c801d494db5b84b3cb9de2ff202f8393f9f`: 0 → 1 (reason updated)
- `D07` / `750b68efb2c65607b74449fdb3094ba583bff80db9c84a843eebaa8d4b86ab8a`: 1 → 1 (reason updated)
- `D07` / `7aa0a5bbc2a0fa31258638f65e60ed2ebe2878f88174035041d365430c7ffaf9`: 1 → 0 (reason updated)
- `D07` / `7f2134e566e3b4025ada30ab64ec93e1938f954d60c07c794960ce3bfbd71e1c`: 1 → 1 (reason updated)
- `D07` / `801bd4e4b95586ec3f8d43f5102cb1c86e741098129f712fedabb7662a15e75a`: 1 → 1 (reason updated)
- `D07` / `845783cf64a5f3428c87acc286629ca93bb4aebaedf25f37cf85b885b385ae0a`: 0 → 1 (reason updated)
- `D07` / `9438e3ebaad299edeed84b07eb5295201e6c8b9bb42480a501960a90bc1abe23`: 0 → 0 (reason updated)
- `D07` / `946db8be364618213ade0c1486c2757ecb23cd4954f24aab26934dc76b8691a9`: 0 → 0 (reason updated)
- `D07` / `997fba76adde54001f21cf5251c5bbf9669dca1508df7958ac7c5ff2e98e1c8e`: 0 → 0 (reason updated)
- `D07` / `a505a4b8e08e774e90c07d5e6a5bd85007bf26e2cc7aa2ccaf7d1dd0c7e556ab`: 0 → 0 (reason updated)
- `D07` / `a8cdc6bf42c1a0198b7f0a4cc0343429126b3d995875fe2234ee5062b851a31c`: 0 → 1 (reason updated)
- `D07` / `abf95415ed31c94dadfa865ee84eaa27d44763457a5ace6a96d535252403ce14`: 1 → 1 (reason updated)
- `D07` / `b11390d8b44348babe9eac38fdc708c23269bc309eb4542fceea8a8d49f0be3f`: 0 → 1 (reason updated)
- `D07` / `d020f9c15777cf7a7d5912073fb59b706f77fc9290dc2ecc307a200e48ade164`: 0 → 2 (reason updated)
- `D07` / `da979564063f28f5401e0c04492a9091fe452046d6820f7ab9b8d7e094c3265e`: 1 → 0 (reason updated)
- `D07` / `df6afdd7c728a381021da4df75bd759f5a2b1d645ba84469a35b70cdc635c4d0`: 0 → 2 (reason updated)
- `D07` / `e5ae52fb2ead45cc7a04d81d458b37e37d18e03d7f237b28ad70c0972c481fe1`: 2 → 0 (reason updated)
- `D07` / `e80428383a1b153e2d6777376de8b918261bf18287f6916da6961b836ab7c1b3`: 0 → 1 (reason updated)
- `D07` / `fa5e9d9c11e3d269d637fa5f4c650a3684a159a9df0136aa607f303996c4f9f5`: 0 → 1 (reason updated)
- `D07` / `fb1baa57236434e2df3136236e897cf4376b962bd2bb77aedf0f4ac1da65c38e`: 0 → 1 (reason updated)
- `D07` / `fda97f7e6fbd794ab5341b567d89e9e29d6bd1ac1428ecff2cdd7729d052f6ae`: 0 → 0 (reason updated)

### D08

- `D08` / `41c37a831d609df88da1d17c9e85dfd4af11b8131d758ad813ea049ede36f064`: 3 → 3 (reason updated)

### D09

- `D09` / `996cca525e9784475b89d39025f1eeccb77338b8fdc24b2ec5f0aac8462f632d`: 0 → 0 (reason updated)
- `D09` / `a4473b46b4783cc3f9685ee561b87c6cd2dbbd8a0660bfa74c84fe95583fc1df`: 0 → 0 (reason updated)

### D10

- `D10` / `742490342448ed58c73fed51a26f9a592de44348e95aa5cdd8a9222b7bf5ce81`: 0 → 0 (reason updated)
- `D10` / `b8dd1df6f664dab8a6dc3ae04a20c21df2ad5b7eb6e3a20d1a0825b838598d64`: 0 → 1 (reason updated)
- `D10` / `f2795c45e5bb167c6d643aeb47738228b6f336d1dff9dfc6b0b75887509983e5`: 0 → 0 (reason updated)

### D11

- `D11` / `14d7dbc8abe3511b30a34077d26d6ef6c2907e65eeff3c8a13f92a64142a2252`: 1 → 1 (reason updated)
- `D11` / `49baea6c805b61fa57716887e6d686b3215bd41cf78c396cb11c33c08fdccc72`: 1 → 1 (reason updated)
- `D11` / `9de8f374a5cb53feefd2d69d6aab746324a454fefa33d52652733d1e404b2013`: 0 → 0 (reason updated)
- `D11` / `a22f06f918c09f040433b497d12cf2ef4ff3421cb34f86fd3fddb27cb6f5e255`: 1 → 0 (reason updated)
- `D11` / `ee4af5ce29ddc230cd93dd6e7d077cbb9bf9fbefd3e0f1eb8a10e7df11c56f57`: 0 → 1 (reason updated)
- `D11` / `fe9ede057bd3d171662bd156d4bfac3b4b7e75e70f60e1e1a7d2058dbe3cdd4e`: 0 → 0 (reason updated)

### D12

- `D12` / `3f9d6b4471ff119494f731cd531b356f66714c08b4fba64426f70bb2089143ae`: 1 → 1 (reason updated)
- `D12` / `450db2aa73965e1ba49ca7ecb2ec46692e03a4a78b6f0ddd9f39564f1bf65271`: 0 → 0 (reason updated)
- `D12` / `4b71542495b8c177215f5f80897b4e6e6b57b04e8c05fa6346850a564e747e21`: 2 → 1 (reason updated)
- `D12` / `594916f1d81f3e8a591fd9663ebae31af3bafc3de1289f3cff87f4db6e4e0956`: 0 → 0 (reason updated)
- `D12` / `6f4a7377a9f19cab0dcbff79f8087c801d494db5b84b3cb9de2ff202f8393f9f`: 0 → 0 (reason updated)
- `D12` / `a6557bebcac9bd0929d4e5f16012d60f4d1dc40a0310e846d99f260f1eed9300`: 0 → 0 (reason updated)
- `D12` / `c01fe224f4e349891a21b380ea8b7e8f9e7fdae6cb2c2b32751cb465aad90829`: 0 → 0 (reason updated)
- `D12` / `f4c543f4e6a45f2d8e64819b8c50058eb33f20cb8b00fa366755638b3238f8f8`: 0 → 0 (reason updated)

### D13

- `D13` / `035aef72d16ad9d706845e40b9472812ed8c5b7d4622092fe7da60d874248af3`: 1 → 1 (reason updated)
- `D13` / `05d2aa5cd4aef3122dc227a0abdbf647232fb0e2710e97afe793a3750db899f7`: 0 → 0 (reason updated)
- `D13` / `06054d4972c7fa5e03b28d267e478ebf4c8d863f4e449a95a4f9f5d98505fa8f`: 0 → 0 (reason updated)
- `D13` / `06d67aca91baafaddfb9983c14fb1705d8b93a4f25a02f1ff5328868cecfd00a`: 0 → 0 (reason updated)
- `D13` / `0db7506fc9087bb425c122efc2afc03e0356baf7ffa70c2b426a3edf8e059d72`: 0 → 0 (reason updated)
- `D13` / `0e06ddeb02b7c9a394c64d63235c50536aee41dbcff6251eccf4f2f470d65b0f`: 2 → 2 (reason updated)
- `D13` / `0e4e1ac51b1c8133020c587553e9356da9d168272f44485464a4baac9481b198`: 0 → 0 (reason updated)
- `D13` / `10e1d51eab85b39ccfcfc50d584878a78df6ff810a3264d546a4fcf7fc1aff99`: 1 → 0 (reason updated)
- `D13` / `1252caaec75ace55a966676f033e0996318d915687d80b7e131a200cf8a617dd`: 0 → 1 (reason updated)
- `D13` / `136a0addffa42f89e4fc88aa85b9f64de3372cdbb916edd32353b09ddeeb2ad3`: 0 → 0 (reason updated)
- `D13` / `15f4b4b412fb938eeba677a2849e59164a725825af28f9a9660cab903370b900`: 0 → 0 (reason updated)
- `D13` / `1730f2fa4bca3c7253dcbf49a8e1632f0cff4f3eac3aab230b2f9cd8ec7585eb`: 1 → 2 (reason updated)
- `D13` / `18d271b210c912ee73845bd21fd724a42b238c1f38fc86e2c4c3f0d6c2d11d6e`: 0 → 0 (reason updated)
- `D13` / `1908e721ec601d7f70e76b5687ffe99ddf52fb487d44d7eb46983c0f1d8d9b43`: 1 → 2 (reason updated)
- `D13` / `1f67b422692d7a3581f3c2772de2b8b7536d89ec4e91513f38a9f2865e035b94`: 0 → 0 (reason updated)
- `D13` / `1f96216f18a54876792fb687481363cb4d764afb7fd42ddbc33a2f50da020476`: 0 → 0 (reason updated)
- `D13` / `21260eaebb9efc7eccb5f0186dc8f19d94cf7dbae6380eb029be197f35cecf99`: 0 → 0 (reason updated)
- `D13` / `213ffb231a6dd0802d54ac4cc329a1ae63b93e73994a5d39b285339d1c5cb278`: 0 → 0 (reason updated)
- `D13` / `217e6d916fd361c12f834401253ce023be6a2282fb3ee320bed2fa7e66deeabe`: 0 → 0 (reason updated)
- `D13` / `2379afbeb225048c26309702e4e284475072522247b71ca5d43e3fd27c5d4050`: 0 → 0 (reason updated)
- `D13` / `2536abc35845de1680e0ab2f2fffad9359dcff9728ef16f4cf2fc3d3f3d90c1b`: 2 → 2 (reason updated)
- `D13` / `26daa2fa4f20613146281a503e895cd17c85199b9808240ffcda5602824534c7`: 0 → 1 (reason updated)
- `D13` / `26e125699ac3c4254b6b9b94b3b6b946d99817b5d91423b74e3beb11bf9bcd93`: 0 → 0 (reason updated)
- `D13` / `2b8aa5171b5117efeaccc74aa6ba1d6d90b6e697e0e81d7076dc7c866f9d81eb`: 0 → 0 (reason updated)
- `D13` / `2bdabc9fbf39f8c14ebb54d2a96ddc9e86f4ac7f321c8dcde8439f4001c301fe`: 2 → 2 (reason updated)
- `D13` / `2c150868b01fc84d96fa37c2d21b325c6d10e8c7113bf952013b359eb83d69f3`: 0 → 1 (reason updated)
- `D13` / `2c15455278291b9a88148a4162e1482c92a5d5bea94ada1765878fed5aa68a21`: 2 → 2 (reason updated)
- `D13` / `2c3a00d419d5abc20249347fed37a576f63446e5854314099ee952cb42787f2d`: 0 → 0 (reason updated)
- `D13` / `33f2e5b94d50c54e2b4bbaefe824474e0524f7ea0f0acbc96902a196b57e2aad`: 0 → 0 (reason updated)
- `D13` / `34f9645a84a07b4d58efa4030330af23159b073ae23e84c8e22ee09608d7c1c2`: 0 → 0 (reason updated)
- `D13` / `352e426adaab7113798d49ee31a02e0d82900ed5af7db7d0770d25052be2d07f`: 0 → 0 (reason updated)
- `D13` / `37316cec092abcf54e13776c8340551fff2e032156ce917fb2178450d4960fcb`: 1 → 1 (reason updated)
- `D13` / `3ca002120d1706af69dab8c20a8de501b225cd6b9890f8efe7fab0b0cd6487a0`: 1 → 1 (reason updated)
- `D13` / `3cb860cf5e8923c35325b974326ef1956ad20b591b894ccd5b2e05c8e5b4dcc3`: 0 → 0 (reason updated)
- `D13` / `3ccb59fb20b7a0c8d8626fd8da2dba93c1a1bfb8b9e79c4b5b60d114d49a1bf3`: 0 → 1 (reason updated)
- `D13` / `3e23709274b6dd92ed220c8e27e4813b373e03a3fda4a27c29eb8e18b731985f`: 0 → 1 (reason updated)
- `D13` / `422b4673849a2ffeb3196f613b0184d3ba241fa02096232390da7940b5357e2e`: 0 → 0 (reason updated)
- `D13` / `42e7c00631b2f6015842b8bf9edcd70ccee5c20c6a2e6f693667ba721ddc7c94`: 2 → 2 (reason updated)
- `D13` / `45ab6e4b4cfa44dcc698353ffc9685e9deac8217e391691c0ec1f715373e29d4`: 0 → 0 (reason updated)
- `D13` / `45d1badbce47ad7ee4bce45d2a1c06ad11d32acb1aefb4b7d74dd94d0cfb02d6`: 0 → 0 (reason updated)
- `D13` / `46bb37f264128f6708a3a0f967031c37f6af886df5485278b6cc687f387dac0b`: 0 → 0 (reason updated)
- `D13` / `46ebdeb51e7764e62b8af52a252f0def5816f541ef0567e1a456bd596aa8e82b`: 1 → 1 (reason updated)
- `D13` / `48beedee7553a19eece014b66ae60e913205c3c50431339371060a66e2596de5`: 0 → 0 (reason updated)
- `D13` / `4cc0aa7c04857e6c4c55f6c162d4f773c6d115b3849332cc0fecfff98e6b445d`: 0 → 0 (reason updated)
- `D13` / `4d4c11c39d53a0098d4cf11038233fd37f969ece9269627818b154a8840fca17`: 0 → 0 (reason updated)
- `D13` / `4d653e6df3a6292a999bf1156b00088480c07480a97f51d1697e3ff300b70b27`: 1 → 2 (reason updated)
- `D13` / `4e7bc254c255a3025c6fecd14a5410eb0cd90e031e76abdb8a8a3242f9c9de70`: 1 → 1 (reason updated)
- `D13` / `5692f3679217f1d926c71ce5ffa54e37897e5c982efdc6a57bae0ce32ca45229`: 2 → 2 (reason updated)
- `D13` / `59520d0fc0e9e67a2279840e27781832c69c8fffca33331fc57026c9e88e7fea`: 0 → 0 (reason updated)
- `D13` / `5b17d55eb9caa3b325c5db76ca8a187ff21c9ea7bd6964040c81178b812dd9ec`: 1 → 0 (reason updated)
- `D13` / `5b30da3e6b17c1529cc88fb44cfcbcdbea8adf1736330ddcbf7046b08b372093`: 0 → 0 (reason updated)
- `D13` / `5b789e6304f818929c07be7a6247ec2801c6cd7a7d38adc1ef9157be61d7ec70`: 0 → 0 (reason updated)
- `D13` / `5fd51c2d0335d316944fbcf1216d686136f03f35b9ed5cad15f029efa120bdfa`: 0 → 0 (reason updated)
- `D13` / `614e6fdeae9ef357a95e36f414beafc9c2e2f018ac97ed58717af1070bd79c15`: 0 → 1 (reason updated)
- `D13` / `642bb98d7f0ba5b986a1b80cdc1a578377fcfabb2fd02e13e96492b3fdd56111`: 0 → 0 (reason updated)
- `D13` / `647409e02fed50c565964a1cd52f7be6b115be22db5431a9ebf208dd8e7b91ee`: 0 → 1 (reason updated)
- `D13` / `663dbe50482bee792d4c883fa3d4dab004ea1ad3a7f991b2c3e668bfc7ac355d`: 0 → 0 (reason updated)
- `D13` / `6a055671f492c9bc195a87362daefb6afdc6b929479864adb9126ac07bc90867`: 0 → 0 (reason updated)
- `D13` / `6aeca7c94f9033509c867fa52db4abc6a60426e71c7809ec933c706d47f141e1`: 0 → 0 (reason updated)
- `D13` / `6c1e2e657e09360a7b67bf530cfdfaccf2bdeab2fcbc99aa67c3e7b0c884c1dd`: 2 → 2 (reason updated)
- `D13` / `6d4d664f4a098f4d1bc6c8d085b9f71b46e9dcf1b67c5c3e5dd1bf2d7e31f062`: 0 → 1 (reason updated)
- `D13` / `6dfb75261e2d390a2c32baa301c1db29147cc063b7e5a0efebc662ffae76c4ae`: 0 → 0 (reason updated)
- `D13` / `6f2336b62b7eacc2588aa0cad209a2da0f824ac94a76d8e9af632f2174f01140`: 2 → 2 (reason updated)
- `D13` / `72b4f15646f4c42d859ef3a8e38170434f89f7d629ac821d88740355eafb5155`: 0 → 1 (reason updated)
- `D13` / `72c63b96160abf77a2ad6fa6c1e8ce5fe4dc6d722b3c846e66572199fa98fadb`: 0 → 0 (reason updated)
- `D13` / `735a29ce43ca1bf4a2289f739511a361c88394c7130ce22b6a30f140fd9d02d9`: 0 → 1 (reason updated)
- `D13` / `73e71d4a9a25dc96ffee9cf4353ef6ac8df780ae14a79ab3818ab44701e6611f`: 2 → 2 (reason updated)
- `D13` / `750b68efb2c65607b74449fdb3094ba583bff80db9c84a843eebaa8d4b86ab8a`: 0 → 0 (reason updated)
- `D13` / `75752c54c87bf26cbbb373bad978c604df3d6fe82aed99b58b1b1b26a227ca04`: 0 → 0 (reason updated)
- `D13` / `7884bc53a8dc3efc6b8c28c8eec5a3c6f1465ac50d3bbfc3d863e299121109be`: 0 → 1 (reason updated)
- `D13` / `7a0ae83903667eb0df4828daf633522e65d8f9ea491be2a1ff52ab2c7cdf6eab`: 0 → 0 (reason updated)
- `D13` / `7a24809848244153908a40867e3ffe81a4b3ab29e541126f88ec78efb7180951`: 0 → 1 (reason updated)
- `D13` / `7a7c1b95dcd3d32c35b2034abad45fc2f8c233280805727c865e91c6c6de3b77`: 0 → 0 (reason updated)
- `D13` / `7a7e39cdfa90a96b66d22c621a3da6d0150837a61c487ab9add7a2ddc05626bf`: 0 → 0 (reason updated)
- `D13` / `7aa0a5bbc2a0fa31258638f65e60ed2ebe2878f88174035041d365430c7ffaf9`: 2 → 2 (reason updated)
- `D13` / `7cedad69d6a4a363e98b155be9dc483a904d84cbddfb1a5d4bdbaeb82afb1cae`: 0 → 0 (reason updated)
- `D13` / `7de6ac480a593924f9ec34032631f42cd0adb7529e5569931b3933919b889500`: 0 → 0 (reason updated)
- `D13` / `7f2134e566e3b4025ada30ab64ec93e1938f954d60c07c794960ce3bfbd71e1c`: 2 → 1 (reason updated)
- `D13` / `801bd4e4b95586ec3f8d43f5102cb1c86e741098129f712fedabb7662a15e75a`: 0 → 0 (reason updated)
- `D13` / `827bc37e1f0122cf9423b6bee5a893ad64f8c3802af229f7c6fa990ad42f9b33`: 0 → 0 (reason updated)
- `D13` / `845783cf64a5f3428c87acc286629ca93bb4aebaedf25f37cf85b885b385ae0a`: 0 → 0 (reason updated)
- `D13` / `84c759c26d569d219a467ab4fcd22a3f8d2103bdfa9ddffd83baf77323104b5e`: 0 → 0 (reason updated)
- `D13` / `8714d43e5d89fa1f5af1f8bf7d53e9d9ae0a6d4324ac592424e667933a35ad0f`: 0 → 1 (reason updated)
- `D13` / `87d94669b87e18025a8f460d1584f494e8a16160dd9b0cce75d80126374ac448`: 1 → 1 (reason updated)
- `D13` / `89d04d93e1e6ecff3df3e947a34b9c68841b6ff939682f31f8de0c157005c7ad`: 0 → 0 (reason updated)
- `D13` / `8b3f85c5a764a23cb070a2b9a98a06ebc878c7d6840b6dcccd1b23db7029b98d`: 0 → 0 (reason updated)
- `D13` / `8db98629874cba2dff5fcc4d166f6cb3b0f883dc16c83d2857069dc6f3fa7d99`: 1 → 1 (reason updated)
- `D13` / `8e300d8e0e59238a5e6054bd09b3a5761dbd0bbabdad84c91bc2b6b10ec4c382`: 0 → 0 (reason updated)
- `D13` / `905a6358eb92f61faf3469e104aa5581e324784d6f33c80d8aa1b0ab4365b17d`: 0 → 1 (reason updated)
- `D13` / `9438e3ebaad299edeed84b07eb5295201e6c8b9bb42480a501960a90bc1abe23`: 0 → 1 (reason updated)
- `D13` / `984b9928ec8b991d356c12004f8e72c61839d3057d6f553d4fd52bbf3001f0cf`: 1 → 1 (reason updated)
- `D13` / `988bc22270e59bfe02d4a049e56ee4ae8bbc9b674af9d7311269bd737e4ae07e`: 1 → 1 (reason updated)
- `D13` / `990c774d7f04c2660cae0242c78b32e5be856900f5fbfa03ed9a99018b3d284a`: 1 → 0 (reason updated)
- `D13` / `997fba76adde54001f21cf5251c5bbf9669dca1508df7958ac7c5ff2e98e1c8e`: 3 → 3 (reason updated)
- `D13` / `9f26c35c0f71488c930eb36f388aae8c5825e5f060970ac55a65e25c9c50230a`: 0 → 0 (reason updated)
- `D13` / `a2beac635b1650fe855df0aad91596d738a015deb7cfd47aa240257771e9d2d1`: 0 → 0 (reason updated)
- `D13` / `a505a4b8e08e774e90c07d5e6a5bd85007bf26e2cc7aa2ccaf7d1dd0c7e556ab`: 1 → 1 (reason updated)
- `D13` / `a8cdc6bf42c1a0198b7f0a4cc0343429126b3d995875fe2234ee5062b851a31c`: 0 → 1 (reason updated)
- `D13` / `abf95415ed31c94dadfa865ee84eaa27d44763457a5ace6a96d535252403ce14`: 0 → 0 (reason updated)
- `D13` / `afb623ac82cb49c490f6178cb4d6f6676bceee358cbd65ca3b3ebe7067e171e0`: 1 → 0 (reason updated)
- `D13` / `b11390d8b44348babe9eac38fdc708c23269bc309eb4542fceea8a8d49f0be3f`: 1 → 1 (reason updated)
- `D13` / `b6d63059ce295a71623f2619db319c7940f6c1e6cd0ea32cd0136dc3f9c23aa2`: 0 → 1 (reason updated)
- `D13` / `b7909f8034e95349dc09d7a9f96b02fe1be2e8d7e9f65e6f55870dd6ec966014`: 0 → 0 (reason updated)
- `D13` / `ba146da8855cb2e87fde22dbd13539aa41a9e7d91bb8353caf283935f04f50cc`: 1 → 0 (reason updated)
- `D13` / `ba4d29e30e17ed181b9a801a7dd348b630aa6de5ffe9e543418be9ef634ce083`: 0 → 1 (reason updated)
- `D13` / `ba4edf25045118eb3c58e6732e550250b59f532621a4efcd7650c8bd206bc875`: 0 → 0 (reason updated)
- `D13` / `ba9d274595731a5090648f44a6d06ac5135f99399e4ae3a58ae1096395639604`: 0 → 0 (reason updated)
- `D13` / `bba007821c13a050afd93e05656072deb427f1e6dd637bbd0c334b2337418938`: 1 → 1 (reason updated)
- `D13` / `bc5cb4fb2a79897b37f231244e43e363efa52ca78a0bcbf249968d8d5c839ad6`: 0 → 0 (reason updated)
- `D13` / `bc7240092d533116c28a3654919125ebaa168e07c1541e30d7a839fb1aa185b7`: 0 → 0 (reason updated)
- `D13` / `becafdb1fbc3448f730348c52a1f6d9c45b495321b5c09a89966f5722efd6f13`: 0 → 0 (reason updated)
- `D13` / `bf76f8d7037df57bf0e9d86ef360038af9f4ac42762aec240538b80866fce21b`: 0 → 0 (reason updated)
- `D13` / `c3d65f33ea58fce3289ec9554ae8a3fccc0ffb19b57b4254596035504e650224`: 0 → 2 (reason updated)
- `D13` / `c85f2d46586b6ab127ce9718302e6586fbbcaabb2793e2245a13732274d66fc7`: 0 → 0 (reason updated)
- `D13` / `cde24b55f6aef902743721fe43911adceb3f01e7cb1b8f1e23a15442434cbded`: 0 → 1 (reason updated)
- `D13` / `ce0d54cd85f28e1af34dc2a8c2b5ed6b4f27c11e2a5f0fc83e0bf91a58b40772`: 1 → 1 (reason updated)
- `D13` / `d020f9c15777cf7a7d5912073fb59b706f77fc9290dc2ecc307a200e48ade164`: 1 → 0 (reason updated)
- `D13` / `d270a5668d0d62035d266c0463151cff7519f60cef06a248361f6ec3a56ad79b`: 0 → 0 (reason updated)
- `D13` / `d438174eb8e672ea44d05a851d8d1b25d8a26bc67815fa696a82d2073bce9b1e`: 0 → 0 (reason updated)
- `D13` / `d6526640ee4d71cdbb712ab35290e8729603a2f949e58ccd862a23d09f5bb85b`: 0 → 0 (reason updated)
- `D13` / `d970866c328834750c21a1a5cb53e76b10f7c21c5668d5545f43e5aca54653e2`: 0 → 0 (reason updated)
- `D13` / `da979564063f28f5401e0c04492a9091fe452046d6820f7ab9b8d7e094c3265e`: 1 → 2 (reason updated)
- `D13` / `dadc1b2663a61cc8632bfa38c3840785a022602980d76caeaec81f5af1d03d1f`: 0 → 0 (reason updated)
- `D13` / `df6afdd7c728a381021da4df75bd759f5a2b1d645ba84469a35b70cdc635c4d0`: 1 → 0 (reason updated)
- `D13` / `e0eba9a3b0d3b66b4dc4bcbc549ce117a7e919ddb28f5827c90b3a0d29554c46`: 1 → 1 (reason updated)
- `D13` / `e48f4684c3f9bd6babcb8617c5eb575a26df3ad201d36c8557c3f77e242255ee`: 1 → 0 (reason updated)
- `D13` / `e5ae52fb2ead45cc7a04d81d458b37e37d18e03d7f237b28ad70c0972c481fe1`: 2 → 2 (reason updated)
- `D13` / `e7771931736a47bd6deee76d77858a62cd8afbd2e872683bb85c3dd07f0d96af`: 0 → 0 (reason updated)
- `D13` / `e80428383a1b153e2d6777376de8b918261bf18287f6916da6961b836ab7c1b3`: 1 → 1 (reason updated)
- `D13` / `ef41dfc97a2efc12a2ee4819256c9c41daf4e2d6e91c241519b4c8773d9016ad`: 0 → 2 (reason updated)
- `D13` / `f04e2426bdf261b949ec86b68249f55d0c890ac4347bfa291e3529c398e0a328`: 0 → 1 (reason updated)
- `D13` / `f115c1a391ad9d66e4fe01a828022ff3bb67bb6684c23fd1691cf10dda1928f7`: 2 → 2 (reason updated)
- `D13` / `f1950266f4b386a0a8b103f5c406584b1e2e0ff372cbc9ea9d5986c410880e70`: 2 → 2 (reason updated)
- `D13` / `f44c97c0623f67b28d04d57b8e68373b34a7c15386256c1c26d38a0aab3ed42c`: 0 → 0 (reason updated)
- `D13` / `f4d450d566877a586e3df6cd7870e7f40bdc49cfdaaf151abdb699daffaf5dce`: 0 → 2 (reason updated)
- `D13` / `f71e952c77917afd9648210d8331c7f4325d27c7d79b8967ec4ff8b39bf48a30`: 0 → 0 (reason updated)
- `D13` / `f74b8ab29f98aea7b2ef83305b88c32e2af768caff426abee13d02f0df7aaae7`: 0 → 0 (reason updated)
- `D13` / `fa5e9d9c11e3d269d637fa5f4c650a3684a159a9df0136aa607f303996c4f9f5`: 0 → 0 (reason updated)
- `D13` / `fb1baa57236434e2df3136236e897cf4376b962bd2bb77aedf0f4ac1da65c38e`: 0 → 0 (reason updated)
- `D13` / `fc1e2a0480c99eddcfc92cbaa34058b35e669bf7590dfb441722a80847a2dc25`: 0 → 0 (reason updated)
- `D13` / `fda97f7e6fbd794ab5341b567d89e9e29d6bd1ac1428ecff2cdd7729d052f6ae`: 0 → 0 (reason updated)
- `D13` / `fdfd398d04386f7016982148b5128a0970a72a635cbc1cd14cbf51780675fe45`: 2 → 2 (reason updated)
- `D13` / `fe592958b804a58a19ec33722cd9cbac36920a5004b0a7ff49ba29998ec31b28`: 0 → 0 (reason updated)
- `D13` / `fe6ad5ecc68e4032d37d444168dcc4809d2f4b65b889f54a9f6033c9780ce20c`: 0 → 0 (reason updated)
- `D13` / `fe9fc85c142e5eccc012af8dad87a347e32ff5feb3a64fe95aa5f4b98ca7bc03`: 0 → 1 (reason updated)

## 제한과 확인 범위

- D07–D13: 7/7 사례, 600/600 passage; 누락·중복 판정 키 없음. 이 범위에서 판정 불가로 제외한 항목은 없다.
- 평가는 AI 단독이며 사람 검수자는 참여하지 않았다.
- 검색 결과·검색 순위, 점수, 구성 설정은 확인하지 않았다. 확인한 입력은 `part-3.json`의 질문·필수 주장·passage이며, 판정 결과는 위 JSON 파일이다.
- 범위 검증은 각 사례의 `chunk_id`와 `(case_id, chunk_id)` 키의 1:1 일치, 점수 0–3, 비어 있지 않은 한국어 이유로 수행했다.
