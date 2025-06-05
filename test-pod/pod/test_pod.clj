(ns pod.test-pod
  (:refer-clojure :exclude [read read-string])
  (:require [bencode.core :as bencode]
            [cheshire.core :as cheshire]
            [clojure.edn :as edn]
            [clojure.java.io :as io]
            [cognitect.transit :as transit])
  (:import [java.io PushbackInputStream]
           [java.net ServerSocket])
  (:gen-class))

(def debug? true)

(defn debug [& args]
  (when debug?
    (binding [*out* (io/writer "./log.txt" :append true)]
      (apply println (cons (str "pod> " (java.util.Date.) ": ") args)))))

;; ***** TEST FUNCTIONS *****

(defn deep-merge
  "Recursively merges maps. If a key exists in both maps a
  maps,they are merged recursively. Otherwise, the value f
  takes precedence."
  [m1 m2]
  (cond
    (nil? m1) m2
    (nil? m2) m1
    (and (map? m1) (map? m2))
    (merge-with (fn [v1 v2]
                  (if (and (map? v1) (map? v2))
                    (deep-merge v1 v2)
                    v2))
                m1 m2)
    :else m2))



;; **************************

(defn write [stream v]
  (bencode/write-bencode stream v)
  (flush))

(defn read-string [^"[B" v]
  (String. v))

(defn read [stream]
  (bencode/read-bencode stream))

#_(def dependents
  (for [i (range 10)]
    {"name" (str "x" i)
     "code"
     (if-not (zero? i)
       (format "(def x%s (inc x%s))" i (dec i))
       "(def x0 0)")}))

(defn transit-json-read [^String s]
  (with-open [bais (java.io.ByteArrayInputStream. (.getBytes s "UTF-8"))]
    (let [r (transit/reader bais :json {:handlers
                                        {"local-date-time"
                                         (transit/read-handler
                                          (fn [s]
                                            (java.time.LocalDateTime/parse s)))
                                         "java.array"
                                         (transit/read-handler
                                          (fn [v]
                                            (into-array v)))}})]
      (transit/read r))))

(defn transit-json-write [s]
  (with-open [baos (java.io.ByteArrayOutputStream. 4096)]
    (let [w (transit/writer baos :json {:handlers
                                        {java.time.LocalDateTime
                                         (transit/write-handler
                                          "local-date-time"
                                          str)}
                                        :default-handler
                                        (transit/write-handler
                                         (fn [x] (when (.isArray (class x)) "java.array"))
                                         vec)})]
      (transit/write w s)
      (str baos))))

(defn transit-json-write-meta [s]
  (with-open [baos (java.io.ByteArrayOutputStream. 4096)]
    (let [w (transit/writer baos :json {:transform transit/write-meta})]
      (transit/write w s)
      (str baos))))


(defn run-pod [cli-args]
  (let [format (cond (contains? cli-args "--json") :json
                     (contains? cli-args "--transit+json") :transit+json
                     :else :edn)
        write-fn (case format
                   :edn pr-str
                   :json cheshire/generate-string
                   :transit+json transit-json-write)
        read-fn (case format
                  :edn edn/read-string
                  :json #(cheshire/parse-string % true)
                  :transit+json transit-json-read)
        socket (= "socket" (System/getenv "BABASHKA_POD_TRANSPORT"))
        [in out] (if socket
                   (let [server (ServerSocket. 0)
                         port (.getLocalPort server)
                         pid (.pid (java.lang.ProcessHandle/current))
                         port-file (io/file (str ".babashka-pod-" pid ".port"))
                         _ (.addShutdownHook (Runtime/getRuntime)
                                             (Thread. (fn [] (.delete port-file))))
                         _ (spit port-file
                                 (str port "\n"))
                         socket (.accept server)
                         in (PushbackInputStream. (.getInputStream socket))
                         out (.getOutputStream socket)]
                     [in out])
                   [(PushbackInputStream. System/in)
                    System/out])]
    (try
      (loop []
        (let [message (try (read in)
                           (catch java.io.EOFException _
                             ::EOF))]
          (when-not (identical? ::EOF message)
            (let [op (get message "op")
                  op (read-string op)
                  op (keyword op)]
              (case op
                :describe
                (do (write out {"format" (case format
                                           :edn "edn"
                                           :json "json"
                                           :transit+json "transit+json")
                                "readers" {"my/tag" "identity"
                                           ;; NOTE: this function is defined later,
                                           ;; which should be supported
                                           "my/other-tag" "pod.test-pod/read-other-tag"}
                                "namespaces"
                                [{"name" "pod.test-pod"
                                  "vars" [{"name" "add-one"}
                                          {"name" "deep-merge"}]}]
                                "ops" {"shutdown" {}}})
                    (recur))
                :invoke (let [var (-> (get message "var")
                                      read-string
                                      symbol)
                              id (-> (get message "id")
                                     read-string)
                              args (get message "args")
                              args (read-string args)
                              args (read-fn args)]
                          (debug "var: " var " args: " args)
                          (case var
                            pod.test-pod/add-one
                            (try (let [ret (inc (first args))]
                                   (write out
                                          {"value" (write-fn ret)
                                           "id" id
                                           "status" ["done"]}))
                                 (catch Exception e
                                   (write out
                                          {"ex-data" (write-fn {:args args})
                                           "ex-message" (.getMessage e)
                                           "status" ["done" "error"]
                                           "id" id})))
                            pod.test-pod/deep-merge
                            (try (let [ret (deep-merge (first args) (second args))]
                                   (write out
                                          {"value" (write-fn ret)
                                           "id" id
                                           "status" ["done"]}))
                                 (catch Exception e
                                   (write out
                                          {"ex-data" (write-fn {:args args})
                                           "ex-message" (.getMessage e)
                                           "status" ["done" "error"]
                                           "id" id}))))
                          (recur))
                :shutdown (System/exit 0)
                :load-ns (let [ns (-> (get message "ns")
                                      read-string
                                      symbol)
                               id (-> (get message "id")
                                      read-string)]
                           (case ns
                             pod.test-pod.loaded
                             (write out
                                    {"status" ["done"]
                                     "id" id
                                     "name" "pod.test-pod.loaded"
                                     "vars" [{"name" "loaded"
                                              "code" "(defn loaded [x] (inc x))"}]})
                             pod.test-pod.loaded2
                             (write out
                                    {"status" ["done"]
                                     "id" id
                                     "name" "pod.test-pod.loaded2"
                                     "vars" [{"name" "x"
                                              "code" "(require '[pod.test-pod.loaded :as loaded])"}
                                             {"name" "loaded"
                                              "code" "(defn loaded [x] (loaded/loaded x))"}]}))
                           (recur)))))))
      (catch Exception e
        (binding [*out* *err*]
          (prn e))))))

(defn -main [& args]
  #_(binding [*out* *err*]
      (prn :args args))
  (when (= "true" (System/getenv "BABASHKA_POD"))
    (run-pod (set args))))
