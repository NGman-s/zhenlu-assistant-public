interface OnboardingProps {
  onCreate: () => void;
  deviceDisconnected: boolean;
}

export function Onboarding({ onCreate, deviceDisconnected }: OnboardingProps) {
  return (
    <section className="onboarding">
      <div className="onboarding-copy">
        <p className="eyebrow">问诊记录工作台</p>
        <h1>开始一次问诊记录</h1>
        <p className="onboarding-lede">
          新建会话后，可以输入问诊文字或使用音频示例，审核病历草稿。
        </p>
        <button type="button" className="btn btn-primary btn-large" onClick={onCreate} disabled={deviceDisconnected}>
          新建问诊会话
        </button>
        <p className="onboarding-notice">
          当前仅用于虚构病例演示，音频转写为模拟结果。请勿上传真实患者信息。
        </p>
      </div>
    </section>
  );
}
