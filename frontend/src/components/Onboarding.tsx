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
          新建会话后，输入问诊文字或上传音频，生成并审核病历草稿。
        </p>
        <button type="button" className="btn btn-primary btn-large" onClick={onCreate} disabled={deviceDisconnected}>
          新建问诊会话
        </button>
        <p className="onboarding-notice">
          当前用于开发验证，请使用已获授权的测试资料。
        </p>
      </div>
    </section>
  );
}
