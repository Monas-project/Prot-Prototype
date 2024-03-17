import { PushAPI } from "@pushprotocol/restapi";
import { ENV } from "@pushprotocol/restapi/src/lib/constants";
import { ethers } from "ethers";

// channel address
const CANNEL_ADDRESS =
  "eip155:11155111:0x69d3E7219CE2259654EcBBFf9597936BaDF5Be52";

/**
 * createSigner for PushProtocol
 */
const createSignerForPushProtocol = async () => {
  // create signer & provider object
  const signer = new ethers.Wallet(
    process.env.NEXT_PUBLIC_PUSH_PROTOCOL_PRIVATE_KEY!
  );
  const provider = new ethers.JsonRpcProvider(
    process.env.NEXT_PUBLIC_SEPOLIA_RPC_URL!
  );
  // connect
  await signer.connect(provider);
  return signer;
};

/**
 * init PushSDK
 */
const initPushSDK = async () => {
  const signer = await createSignerForPushProtocol();
  const pushUser = await PushAPI.initialize(signer, {
    env: ENV.STAGING,
  });
  return pushUser;
};

/**
 * get PushInfo
 */
export const getPushInfo = async () => {
  // init PushSDK
  const pushUser = await initPushSDK();
  // get profile Info
  const response = await pushUser.profile.info();
  // get notification info
  const listInfo = await pushUser.notification.list("INBOX");
  // get subscriptions
  const subscriptions = await pushUser.notification.subscriptions();
  // get channel info
  const channelInfo = await pushUser.channel.info(CANNEL_ADDRESS);

  console.log("response:", response);
  console.log("listInfo:", listInfo);
  console.log("subscriptions:", subscriptions);
  console.log("channelInfo:", channelInfo);
};

/**
 * send Notification
 */
export const sendNotification = async () => {
  // init PushSDK
  const pushUser = await initPushSDK();
  // send notification
  const sendNotifRes = await pushUser.channel.send(
    ["0x69d3E7219CE2259654EcBBFf9597936BaDF5Be52"],
    {
      notification: {
        title: "This is a test Notification",
        body: "This is a test Notification!!!!!!",
      },
    }
  );
  console.log("sendNotifRes:", { sendNotifRes });
};
